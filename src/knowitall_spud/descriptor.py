"""Validation of caller-supplied SPUD admission descriptors.

A descriptor names the identity, bundle layout and artifact selection of an
already produced SPUD bundle. Validation never runs SPUD, never repairs an
unknown value by inference, and never silently chooses between competing
bundle layouts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .artifacts import ArtifactError, is_digest, safe_relative_path, verify_regular_directories


DESCRIPTOR_VERSION = "knowitall.spud-admission/v1"
READER_PROFILE = "spud-reader/v1"

ARTIFACT_ROLES = (
    "graph",
    "graph_report",
    "citation_index",
    "article",
    "okf_manifest",
    "run_manifest",
    "source_evidence",
    "archive",
)
LAYOUTS = ("current", "legacy", "auto", "explicit")

GRAPH_PATH = "graphify-out/graph.json"
GRAPH_REPORT_PATH = "graphify-out/GRAPH_REPORT.md"
CITATION_INDEX_PATH = "spud-out/json/analysis/inputs/graph-index.json"
OKF_MANIFEST_PATH = "spud-out/manifest.yaml"
RUN_MANIFEST_PATH = "run-manifest.yaml"
CURRENT_ARTICLE_ROOT = "spud-out/markdown"
LEGACY_ARTICLE_ROOT = "spud-out"
LIMITATION_REASONS = (
    "invalid_citation_records",
    "invalid_graph_records",
    "malformed_citation_index",
    "malformed_graph_json",
    "missing_archive",
    "missing_article",
    "missing_bound_graph",
    "missing_citation_index",
    "missing_graph",
    "missing_graph_report",
    "missing_okf_manifest",
    "missing_run_manifest",
    "missing_source_evidence",
    "no_articles_selected",
    "skipped_uploads",
    "unbound_graph_source_files",
    "undecodable_narrative_text",
    "unknown_generator_version",
    "unreadable_manifest_fields",
    "unsupported_artifact_format",
    "unsupported_citation_profile",
    "unsupported_graph_profile",
    "unverified_source_binding",
)

EXCLUDED_ARTICLE_PREFIXES = ("spud-out/site/", "spud-out/json/")

_DESCRIPTOR_KEYS = frozenset(
    {
        "descriptor_version",
        "project_id",
        "repository_id",
        "bundle_id",
        "layout",
        "artifacts",
        "supplied",
        "expected_digests",
        "declared_missing",
        "source_binding",
    }
)


class DescriptorError(ValueError):
    """A supplied admission descriptor is unusable as written."""


@dataclass(frozen=True)
class BundleLimits:
    max_files: int = 2000
    max_artifact_bytes: int = 8 * 1024 * 1024
    max_total_bytes: int = 64 * 1024 * 1024


@dataclass(frozen=True)
class SelectedArtifact:
    role: str
    path: str


@dataclass(frozen=True)
class AdmissionDescriptor:
    descriptor_version: str
    project_id: str
    repository_id: str
    bundle_id: str
    layout: str
    artifacts: tuple[SelectedArtifact, ...]
    supplied: dict[str, str]
    expected_digests: dict[str, str]
    declared_missing: tuple[tuple[str, str], ...]
    source_binding: dict[str, object] | None


def _identity(value: Mapping[str, object], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise DescriptorError(f"descriptor {key} must be a nonempty string")
    return raw


def _string_map(value: Mapping[str, object], key: str) -> dict[str, str]:
    raw = value.get(key, {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise DescriptorError(f"descriptor {key} must be a mapping of strings")
    result: dict[str, str] = {}
    for name, item in raw.items():
        if not isinstance(name, str) or not isinstance(item, str):
            raise DescriptorError(f"descriptor {key} must be a mapping of strings")
        result[name] = item
    return result


def _pairs(value: Mapping[str, object], key: str, *, reasons: tuple[str, ...] | None = None) -> tuple[tuple[str, str], ...]:
    raw = value.get(key, ())
    if raw is None:
        raw = ()
    if isinstance(raw, (str, bytes)) or not hasattr(raw, "__iter__"):
        raise DescriptorError(f"descriptor {key} must be a sequence of (scope, reason) pairs")
    pairs: list[tuple[str, str]] = []
    for entry in raw:
        if isinstance(entry, Mapping):
            scope, reason = entry.get("scope"), entry.get("reason")
        elif isinstance(entry, (list, tuple)) and len(entry) == 2:
            scope, reason = entry
        else:
            raise DescriptorError(f"descriptor {key} must be a sequence of (scope, reason) pairs")
        if not isinstance(scope, str) or not isinstance(reason, str) or not scope or not reason:
            raise DescriptorError(f"descriptor {key} entries must be nonempty strings")
        if reasons is not None and reason not in reasons:
            raise DescriptorError(f"descriptor {key} reason is not supported: {reason!r}")
        pairs.append((scope, reason))
    return tuple(sorted(set(pairs)))


def _selection(value: Mapping[str, object]) -> tuple[SelectedArtifact, ...]:
    raw = value.get("artifacts", ())
    if raw is None:
        raw = ()
    if isinstance(raw, (str, bytes)) or not hasattr(raw, "__iter__"):
        raise DescriptorError("descriptor artifacts must be a sequence of role/path entries")
    selected: list[SelectedArtifact] = []
    for entry in raw:
        if isinstance(entry, Mapping):
            role, path = entry.get("role"), entry.get("path")
        elif isinstance(entry, (list, tuple)) and len(entry) == 2:
            role, path = entry
        else:
            raise DescriptorError("descriptor artifacts must be a sequence of role/path entries")
        if role not in ARTIFACT_ROLES:
            raise DescriptorError(f"descriptor artifact role is not supported: {role!r}")
        if not isinstance(path, str):
            raise DescriptorError(f"descriptor artifact path must be a string: {path!r}")
        try:
            relative = safe_relative_path(path)
        except ArtifactError as error:
            raise DescriptorError(str(error)) from error
        selected.append(SelectedArtifact(role, relative))
    return tuple(selected)


def load_descriptor(value: Mapping[str, object]) -> AdmissionDescriptor:
    if not isinstance(value, Mapping):
        raise DescriptorError("descriptor must be a mapping")
    unknown = sorted(set(value) - _DESCRIPTOR_KEYS)
    if unknown:
        raise DescriptorError(f"descriptor has unsupported keys: {unknown}")
    if value.get("descriptor_version") != DESCRIPTOR_VERSION:
        raise DescriptorError(
            f"unsupported descriptor version: {value.get('descriptor_version')!r}; expected {DESCRIPTOR_VERSION!r}"
        )
    layout = value.get("layout", "auto")
    if layout not in LAYOUTS:
        raise DescriptorError(f"descriptor layout is not supported: {layout!r}")
    artifacts = _selection(value)
    if layout == "explicit" and not artifacts:
        raise DescriptorError("descriptor layout 'explicit' requires an artifact selection")
    if layout != "explicit" and artifacts:
        raise DescriptorError(f"descriptor layout {layout!r} must not enumerate artifacts")
    expected_digests = _string_map(value, "expected_digests")
    for path, digest in expected_digests.items():
        try:
            safe_relative_path(path)
        except ArtifactError as error:
            raise DescriptorError(str(error)) from error
        if not is_digest(digest):
            raise DescriptorError(f"expected digest for {path!r} is not a sha256 digest")
    source_binding = value.get("source_binding")
    if source_binding is not None and not isinstance(source_binding, Mapping):
        raise DescriptorError("descriptor source_binding must be a mapping when supplied")
    return AdmissionDescriptor(
        descriptor_version=DESCRIPTOR_VERSION,
        project_id=_identity(value, "project_id"),
        repository_id=_identity(value, "repository_id"),
        bundle_id=_identity(value, "bundle_id"),
        layout=layout,
        artifacts=artifacts,
        supplied=_string_map(value, "supplied"),
        expected_digests=expected_digests,
        declared_missing=_pairs(value, "declared_missing", reasons=LIMITATION_REASONS),
        source_binding=dict(source_binding) if source_binding is not None else None,
    )


def _articles(bundle_root: Path, root: str) -> tuple[str, ...]:
    base = bundle_root / root
    try:
        verify_regular_directories(bundle_root, root + "/leaf")
    except ArtifactError:
        return ()
    if not base.is_dir() or base.is_symlink():
        return ()
    found = []
    for path in base.rglob("*.md"):
        relative = path.relative_to(bundle_root).as_posix()
        if any(relative.startswith(prefix) for prefix in EXCLUDED_ARTICLE_PREFIXES):
            continue
        if not _present(bundle_root, relative):
            continue
        found.append(relative)
    return tuple(sorted(found))


def _present(bundle_root: Path, relative: str) -> bool:
    """A path is present only as a regular file reached without any symlink."""
    try:
        verify_regular_directories(bundle_root, relative)
    except ArtifactError:
        return False
    path = bundle_root / relative
    return path.is_file() and not path.is_symlink()


def resolve_artifacts(
    bundle_root: Path,
    value: AdmissionDescriptor,
    limits: BundleLimits,
) -> tuple[tuple[SelectedArtifact, ...], tuple[tuple[str, str], ...]]:
    if value.layout == "explicit":
        selected = list(value.artifacts)
    else:
        current = _articles(bundle_root, CURRENT_ARTICLE_ROOT)
        legacy = tuple(path for path in _articles(bundle_root, LEGACY_ARTICLE_ROOT) if path not in current)
        if value.layout == "auto":
            if current and legacy:
                raise DescriptorError(
                    "ambiguous bundle layout: articles found under both "
                    f"{CURRENT_ARTICLE_ROOT!r} and {LEGACY_ARTICLE_ROOT!r}; select a layout explicitly"
                )
            articles = current or legacy
        elif value.layout == "current":
            articles = current
        else:
            articles = legacy
        selected = [SelectedArtifact("article", path) for path in articles]
        candidates = [
            ("graph", GRAPH_PATH),
            ("graph_report", GRAPH_REPORT_PATH),
            ("citation_index", CITATION_INDEX_PATH),
            ("okf_manifest", OKF_MANIFEST_PATH),
            ("run_manifest", RUN_MANIFEST_PATH),
        ]
        bound_manifest = (value.source_binding or {}).get("content_manifest_path")
        if isinstance(bound_manifest, str) and bound_manifest:
            try:
                candidates.append(("source_evidence", safe_relative_path(bound_manifest)))
            except ArtifactError as error:
                raise DescriptorError(str(error)) from error
        for role, path in candidates:
            if _present(bundle_root, path):
                selected.append(SelectedArtifact(role, path))

    roles = {item.role for item in selected}
    limitations = list(value.declared_missing)
    for role, path, reason in (
        ("graph", GRAPH_PATH, "missing_graph"),
        ("graph_report", GRAPH_REPORT_PATH, "missing_graph_report"),
        ("okf_manifest", OKF_MANIFEST_PATH, "missing_okf_manifest"),
        ("run_manifest", RUN_MANIFEST_PATH, "missing_run_manifest"),
    ):
        if role not in roles:
            limitations.append((path, reason))
    if "article" not in roles:
        limitations.append(("spud-out", "no_articles_selected"))
    if len(selected) > limits.max_files:
        raise DescriptorError(
            f"selection of {len(selected)} artifacts exceeds file limit {limits.max_files}"
        )
    ordered = tuple(sorted(selected, key=lambda item: (item.role, item.path)))
    return ordered, tuple(sorted(set(limitations)))
