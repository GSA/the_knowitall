"""Normalization of retained SPUD artifacts into graded evidence records.

Every record keeps the grade that matches how its evidence was produced:
graph nodes and edges are recorded producer artifacts, citation index entries
are citations that never become relationships, report and article text is
inert generated narrative, and manifest fields are retained provenance
assertions. Unknown or unverifiable provenance stays unknown.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .artifacts import RetainedArtifact, is_digest
from .descriptor import GRAPH_PATH, READER_PROFILE, AdmissionDescriptor


GRADE_ARTIFACT = "recorded_artifact"
GRADE_CITATION = "recorded_citation"
GRADE_NARRATIVE = "generated_narrative"
GRADE_PROVENANCE = "retained_provenance"

KIND_SYMBOL = "graph_symbol"
KIND_RELATIONSHIP = "graph_relationship"
KIND_CITATION = "citation_entry"
KIND_PASSAGE = "narrative_passage"
KIND_ASSERTION = "provenance_assertion"

RECORD_KINDS = (KIND_SYMBOL, KIND_RELATIONSHIP, KIND_CITATION, KIND_PASSAGE, KIND_ASSERTION)
EVIDENCE_GRADES = (GRADE_ARTIFACT, GRADE_CITATION, GRADE_NARRATIVE, GRADE_PROVENANCE)

BINDING_UNKNOWN = "unknown"
BINDING_ASSERTED = "asserted"
BINDING_BOUND = "bound"

COMMIT_KEYS = ("commit_sha", "commit", "revision", "source_commit")
PLACEHOLDER_VALUES = frozenset({"", "-", "n/a", "na", "none", "null", "tbd", "unknown", "unset"})
NARRATIVE_ROLES = ("graph_report", "article")
MANIFEST_ROLES = ("okf_manifest", "run_manifest")
OPAQUE_ROLES = ("archive",)
SUPPLIED_SCOPE = "descriptor.supplied"

_KIND_PREFIX = {
    KIND_SYMBOL: "sym",
    KIND_RELATIONSHIP: "rel",
    KIND_CITATION: "cit",
    KIND_PASSAGE: "nar",
    KIND_ASSERTION: "prov",
}


class RecordError(ValueError):
    """A retained artifact cannot be normalized as requested."""


@dataclass(frozen=True)
class Locator:
    artifact_path: str
    content_digest: str
    pointer: str | None = None
    start_line: int | None = None
    end_line: int | None = None


@dataclass(frozen=True)
class SourceReference:
    path: str
    start_line: int | None = None
    end_line: int | None = None


@dataclass(frozen=True)
class ArtifactRecord:
    record_id: str
    kind: str
    grade: str
    name: str
    subject: str | None
    object: str | None
    relation: str | None
    text: str | None
    source_reference: SourceReference | None
    locator: Locator
    attribution: dict[str, str]


@dataclass(frozen=True)
class NormalizedBundle:
    project_id: str
    repository_id: str
    bundle_id: str
    reader_profile: str
    supplied: dict[str, str]
    artifacts: tuple[RetainedArtifact, ...]
    records: tuple[ArtifactRecord, ...]
    limitations: tuple[tuple[str, str], ...]
    artifact_completeness: str
    source_coverage: str
    revision_binding: str
    bound_snapshot: dict[str, str] | None


def _record_id(kind: str, locator: Locator, identity: Sequence[str | None]) -> str:
    payload = json.dumps(
        [kind, locator.artifact_path, locator.content_digest, locator.pointer, locator.start_line, list(identity)],
        separators=(",", ":"),
    )
    return _KIND_PREFIX[kind] + "-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_lines(value: object) -> tuple[int | None, int | None]:
    """Read SPUD's lenient `source_location` into one-based half-open lines."""
    if not isinstance(value, str):
        return None, None
    text = value.strip().lstrip("Ll").strip()
    if not text:
        return None, None
    head, _, tail = text.partition("-")
    try:
        start = int(head.strip().lstrip("Ll") or "")
    except ValueError:
        return None, None
    if start < 1:
        return None, None
    end = start + 1
    if tail.strip():
        try:
            last = int(tail.strip().lstrip("Ll"))
        except ValueError:
            return None, None
        if last < start:
            return None, None
        end = last + 1
    return start, end


def _usable(*values: object) -> bool:
    """A usable contract identity is a string with non-whitespace content."""
    return all(isinstance(item, str) and item.strip() for item in values)


def _source_reference(value: Mapping[str, object]) -> SourceReference | None:
    path = value.get("source_file")
    if not _usable(path):
        return None
    start, end = _source_lines(value.get("source_location"))
    return SourceReference(path, start, end)


def _attribution(value: Mapping[str, object], keys: Iterable[str]) -> dict[str, str]:
    attribution = {}
    for key in keys:
        item = value.get(key)
        if isinstance(item, (str, int, float, bool)) and not isinstance(item, bool):
            attribution[key] = str(item)
        elif isinstance(item, bool):
            attribution[key] = "true" if item else "false"
    return attribution


def _strip_comment(line: str) -> str | None:
    """Remove a trailing comment, honoring quoted scalars.

    Returns None when a quote is left unterminated, so a scalar the reader
    cannot faithfully parse is skipped rather than silently truncated.
    """
    quote: str | None = None
    index = 0
    while index < len(line):
        character = line[index]
        if quote is None:
            if character in "'\"":
                quote = character
            elif character == "#" and (index == 0 or line[index - 1] in " \t"):
                return line[:index].rstrip()
        elif quote == '"' and character == "\\":
            index += 1
        elif character == quote:
            if quote == "'" and line[index + 1 : index + 2] == "'":
                index += 1
            else:
                quote = None
        index += 1
    return None if quote is not None else line.rstrip()


def _scalar(value: str) -> str | None:
    """Read one flat scalar, or None for syntax the reader cannot represent.

    Single quotes are unescaped; a double-quoted scalar carrying backslash
    escape syntax is skipped rather than returned with the escapes intact.
    """
    if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
        inner = value[1:-1]
        if value[0] == "'":
            return inner.replace("''", "'")
        return None if "\\" in inner else inner
    if value[0] in "{[&*!|>'\"":
        return None
    return value


def read_flat_yaml_spans(data: bytes) -> dict[str, tuple[str, int, int]]:
    """Read flat YAML fields with the half-open source line range of each field.

    Only `key: scalar` lines and `key:` blocks of scalars are read. Nested
    mappings, inline collections, anchors, and documents that are not flat
    scalars are ignored rather than guessed at. No YAML tag, alias, or object
    construction is honored.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {}
    lines = text.split("\n")
    fields: dict[str, tuple[str, int, int]] = {}
    index = 0
    while index < len(lines):
        raw = lines[index]
        start_line = index + 1
        index += 1
        if raw.lstrip().startswith("#"):
            continue
        line = _strip_comment(raw)
        if line is None or not line.strip() or line != line.lstrip() or line.startswith("-"):
            continue
        key, separator, value = line.partition(":")
        key = key.strip()
        if not separator or not key or " " in key:
            continue
        value = value.strip()
        if value:
            scalar = _scalar(value)
            probe = index
            while probe < len(lines) and (not lines[probe].strip() or lines[probe].lstrip().startswith("#")):
                probe += 1
            # An indented follower folds into this scalar; the reader cannot
            # represent that, so the whole field is skipped rather than cut short.
            continued = probe < len(lines) and lines[probe] != lines[probe].lstrip()
            if scalar is None or continued:
                continue
            fields[key] = (scalar, start_line, start_line + 1)
            continue
        block: list[str] = []
        scalars = True
        while index < len(lines):
            follower = lines[index]
            if not follower.strip():
                index += 1
                continue
            if follower == follower.lstrip():
                break
            index += 1
            cleaned = _strip_comment(follower)
            if cleaned is None:
                scalars = False
                continue
            item = cleaned.strip()
            scalar = _scalar(item[2:].strip()) if item.startswith("- ") and ":" not in item else None
            if scalar is None:
                scalars = False
            else:
                block.append(scalar)
        if scalars and block:
            fields[key] = (", ".join(block), start_line, index + 1)
    return fields


def read_flat_yaml(data: bytes) -> dict[str, str]:
    """Read flat YAML fields without their source line ranges."""
    return {key: value for key, (value, _start, _end) in read_flat_yaml_spans(data).items()}


def _graph_records(artifact: RetainedArtifact) -> tuple[tuple[ArtifactRecord, ...], tuple[tuple[str, str], ...]]:
    try:
        payload = json.loads(artifact.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return (), ((artifact.path, "malformed_graph_json"),)
    nodes = payload.get("nodes") if isinstance(payload, Mapping) else None
    edges = payload.get("edges", []) if isinstance(payload, Mapping) else None
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return (), ((artifact.path, "unsupported_graph_profile"),)
    for value in nodes + edges:
        if not isinstance(value, Mapping) or "_origin" not in value:
            return (), ((artifact.path, "unsupported_graph_profile"),)

    identities: dict[str, Mapping[str, object]] = {}
    records: list[ArtifactRecord] = []
    for position, value in enumerate(nodes):
        identity = value.get("id")
        label = value.get("label")
        source_file = value.get("source_file")
        if not _usable(identity, label, source_file):
            return (), ((artifact.path, "invalid_graph_records"),)
        if identity in identities:
            return (), ((artifact.path, "invalid_graph_records"),)
        identities[identity] = value
        locator = Locator(artifact.path, artifact.content_digest, pointer=f"/nodes/{position}")
        records.append(
            ArtifactRecord(
                record_id=_record_id(KIND_SYMBOL, locator, (identity,)),
                kind=KIND_SYMBOL,
                grade=GRADE_ARTIFACT,
                name=label,
                subject=identity,
                object=None,
                relation=None,
                text=None,
                source_reference=_source_reference(value),
                locator=locator,
                attribution=_attribution(value, ("_origin", "file_type", "community_name", "confidence")),
            )
        )
    for position, value in enumerate(edges):
        subject = value.get("source")
        target = value.get("target")
        relation = value.get("relation")
        if not _usable(subject, target, relation):
            return (), ((artifact.path, "invalid_graph_records"),)
        if subject not in identities or target not in identities:
            return (), ((artifact.path, "invalid_graph_records"),)
        locator = Locator(artifact.path, artifact.content_digest, pointer=f"/edges/{position}")
        records.append(
            ArtifactRecord(
                record_id=_record_id(KIND_RELATIONSHIP, locator, (subject, relation, target)),
                kind=KIND_RELATIONSHIP,
                grade=GRADE_ARTIFACT,
                name=f"{subject} {relation} {target}",
                subject=subject,
                object=target,
                relation=relation,
                text=None,
                source_reference=_source_reference(value),
                locator=locator,
                attribution=_attribution(value, ("_origin", "confidence", "file_type")),
            )
        )
    return tuple(records), ()


def _citation_records(artifact: RetainedArtifact) -> tuple[tuple[ArtifactRecord, ...], tuple[tuple[str, str], ...]]:
    try:
        payload = json.loads(artifact.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return (), ((artifact.path, "malformed_citation_index"),)
    if not isinstance(payload, list):
        return (), ((artifact.path, "unsupported_citation_profile"),)
    records: list[ArtifactRecord] = []
    for position, value in enumerate(payload):
        if not isinstance(value, Mapping):
            return (), ((artifact.path, "unsupported_citation_profile"),)
        label = value.get("label")
        if not _usable(label):
            return (), ((artifact.path, "invalid_citation_records"),)
        locator = Locator(artifact.path, artifact.content_digest, pointer=f"/{position}")
        records.append(
            ArtifactRecord(
                record_id=_record_id(KIND_CITATION, locator, (label,)),
                kind=KIND_CITATION,
                grade=GRADE_CITATION,
                name=label,
                subject=None,
                object=None,
                relation=None,
                text=None,
                source_reference=_source_reference(value),
                locator=locator,
                attribution=_attribution(value, ("norm_label", "community_name", "file_type")),
            )
        )
    return tuple(records), ()


def _narrative_records(artifact: RetainedArtifact) -> tuple[tuple[ArtifactRecord, ...], tuple[tuple[str, str], ...]]:
    try:
        text = artifact.data.decode("utf-8")
    except UnicodeDecodeError:
        return (), ((artifact.path, "undecodable_narrative_text"),)
    records: list[ArtifactRecord] = []
    lines = text.split("\n")
    start: int | None = None
    buffer: list[str] = []

    def flush(end_line: int) -> None:
        nonlocal start, buffer
        if start is None:
            return
        locator = Locator(artifact.path, artifact.content_digest, start_line=start, end_line=end_line)
        body = "\n".join(buffer)
        records.append(
            ArtifactRecord(
                record_id=_record_id(KIND_PASSAGE, locator, (str(start),)),
                kind=KIND_PASSAGE,
                grade=GRADE_NARRATIVE,
                name=artifact.path,
                subject=None,
                object=None,
                relation=None,
                text=body,
                source_reference=None,
                locator=locator,
                attribution={"role": artifact.role},
            )
        )
        start, buffer = None, []

    for position, line in enumerate(lines, start=1):
        if line.strip():
            if start is None:
                start = position
            buffer.append(line)
        else:
            flush(position)
    flush(len(lines) + 1)
    return tuple(records), ()


def _manifest_records(artifact: RetainedArtifact) -> tuple[tuple[ArtifactRecord, ...], tuple[tuple[str, str], ...]]:
    fields = read_flat_yaml_spans(artifact.data)
    if not fields:
        return (), ((artifact.path, "unreadable_manifest_fields"),)
    records = []
    for key in sorted(fields):
        value, start_line, end_line = fields[key]
        locator = Locator(
            artifact.path, artifact.content_digest, pointer=None, start_line=start_line, end_line=end_line
        )
        records.append(
            ArtifactRecord(
                record_id=_record_id(KIND_ASSERTION, locator, (key,)),
                kind=KIND_ASSERTION,
                grade=GRADE_PROVENANCE,
                name=key,
                subject=None,
                object=None,
                relation=None,
                text=value,
                source_reference=None,
                locator=locator,
                attribution={"role": artifact.role},
            )
        )
    return tuple(records), ()


def _asserted_commit(fields: Mapping[str, object]) -> bool:
    """A commit key counts as asserted only with a real, non-placeholder value."""
    for key in COMMIT_KEYS:
        value = fields.get(key)
        if isinstance(value, str) and value.strip().casefold() not in PLACEHOLDER_VALUES:
            return True
    return False


def _verify_binding(
    binding: Mapping[str, object],
    artifacts: tuple[RetainedArtifact, ...],
    graph_source_files: frozenset[str],
    graph_sources_complete: bool,
) -> tuple[dict[str, str] | None, str | None]:
    graphs = [item for item in artifacts if item.role == "graph"]
    if not graphs:
        return None, "missing_bound_graph"
    if len(graphs) > 1:
        # One binding names one graph digest; it never vouches for a second graph.
        return None, "ambiguous_bound_graph"
    graph = graphs[0]
    graph_digest = binding.get("graph_digest")
    if not is_digest(graph_digest) or graph_digest != graph.content_digest:
        return None, "unverified_source_binding"
    snapshot_id = binding.get("snapshot_id")
    commit = binding.get("commit_sha")
    manifest_digest = binding.get("content_manifest_digest")
    manifest_path = binding.get("content_manifest_path")
    if not all(isinstance(item, str) and item.strip() for item in (snapshot_id, commit, manifest_path)):
        return None, "unverified_source_binding"
    if commit.strip().casefold() in PLACEHOLDER_VALUES:
        return None, "unverified_source_binding"
    if not is_digest(manifest_digest):
        return None, "unverified_source_binding"
    evidence = next(
        (item for item in artifacts if item.role == "source_evidence" and item.path == manifest_path), None
    )
    if evidence is None or evidence.content_digest != manifest_digest:
        return None, "unverified_source_binding"
    try:
        payload = json.loads(evidence.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "unverified_source_binding"
    if not isinstance(payload, Mapping) or payload.get("snapshot_id") != snapshot_id:
        return None, "unverified_source_binding"
    files = payload.get("files")
    if not isinstance(files, list):
        return None, "unverified_source_binding"
    covered = set()
    for entry in files:
        if not isinstance(entry, Mapping):
            return None, "unverified_source_binding"
        path, digest = entry.get("path"), entry.get("content_digest")
        if not isinstance(path, str) or not is_digest(digest):
            return None, "unverified_source_binding"
        covered.add(path)
    if not graph_sources_complete or not graph_source_files <= covered:
        return None, "unbound_graph_source_files"
    if not _asserted_commit(payload) or not any(
        isinstance(payload.get(key), str) and payload[key].strip() == commit.strip() for key in COMMIT_KEYS
    ):
        # Retained evidence must itself associate the snapshot with the commit;
        # matching digests and paths never establish an asserted revision.
        return None, "unbound_commit_evidence"
    return {
        "snapshot_id": snapshot_id,
        "commit_sha": commit,
        "content_manifest_digest": manifest_digest,
    }, None


def normalize_bundle(
    value: AdmissionDescriptor,
    artifacts: tuple[RetainedArtifact, ...],
    limitations: tuple[tuple[str, str], ...],
) -> NormalizedBundle:
    records: list[ArtifactRecord] = []
    found = list(limitations)
    manifest_fields: dict[str, dict[str, str]] = {}
    for artifact in artifacts:
        if artifact.role == "graph":
            produced, issues = _graph_records(artifact)
        elif artifact.role == "citation_index":
            produced, issues = _citation_records(artifact)
        elif artifact.role in NARRATIVE_ROLES:
            produced, issues = _narrative_records(artifact)
        elif artifact.role in MANIFEST_ROLES:
            produced, issues = _manifest_records(artifact)
            manifest_fields[artifact.path] = read_flat_yaml(artifact.data)
        elif artifact.role in OPAQUE_ROLES:
            produced, issues = (), ((artifact.path, "unsupported_artifact_format"),)
        else:
            produced, issues = (), ()
        records.extend(produced)
        found.extend(issues)

    version = value.supplied.get("generator_version")
    if not isinstance(version, str) or not version.strip():
        # A blank supplied version is no version; it is retained but not believed.
        found.append((SUPPLIED_SCOPE, "unknown_generator_version"))
    for path, fields in manifest_fields.items():
        skipped = fields.get("total_files_skipped") or fields.get("skipped_files")
        if skipped is not None and skipped.strip() not in {"0", ""}:
            found.append((path, "skipped_uploads"))

    graph_records = [record for record in records if record.kind in {KIND_SYMBOL, KIND_RELATIONSHIP}]
    graph_source_files = frozenset(
        record.source_reference.path for record in graph_records if record.source_reference is not None
    )
    graph_sources_complete = bool(graph_records) and all(
        record.source_reference is not None for record in graph_records
    )
    asserted = any(_asserted_commit(fields) for fields in manifest_fields.values()) or _asserted_commit(value.supplied)
    bound_snapshot: dict[str, str] | None = None
    revision_binding = BINDING_ASSERTED if asserted else BINDING_UNKNOWN
    source_coverage = "unknown"
    if value.source_binding is not None:
        asserted = asserted or _asserted_commit(value.source_binding)
        bound_snapshot, failure = _verify_binding(
            value.source_binding, artifacts, graph_source_files, graph_sources_complete
        )
        if bound_snapshot is not None:
            revision_binding = BINDING_BOUND
            supplied_coverage = value.source_binding.get("source_coverage")
            # Coverage the caller did not state usably stays unknown, never inferred.
            if isinstance(supplied_coverage, str) and supplied_coverage in {"complete", "partial"}:
                source_coverage = supplied_coverage
        else:
            revision_binding = BINDING_ASSERTED if asserted else BINDING_UNKNOWN
            found.append((GRAPH_PATH, failure or "unverified_source_binding"))

    unique = tuple(sorted(set(found)))
    return NormalizedBundle(
        project_id=value.project_id,
        repository_id=value.repository_id,
        bundle_id=value.bundle_id,
        reader_profile=READER_PROFILE,
        supplied=dict(value.supplied),
        artifacts=artifacts,
        records=tuple(sorted(records, key=lambda item: (item.kind, item.name, item.record_id))),
        limitations=unique,
        artifact_completeness="complete" if not unique else "partial",
        source_coverage=source_coverage,
        revision_binding=revision_binding,
        bound_snapshot=bound_snapshot,
    )
