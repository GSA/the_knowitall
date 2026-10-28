import hashlib
import json
import platform
from dataclasses import dataclass
from pathlib import Path

from .adapter import GraphifyConfig, run_graphify

from knowitall_contract import Coverage, SnapshotRef, SourceRange
from knowitall_snapshot import SnapshotManifest


class GenerationValidationError(ValueError):
    pass


ENGINE_IDENTITY = "graphifyy:0.9.96"
RUNTIME_IDENTITY = "python:" + platform.python_version() + ";tree-sitter:0.25.2;python-grammar:0.25.0;typescript-grammar:0.23.2"
CONFIG_IDENTITY = "sha256:" + hashlib.sha256(b"code-only/no-cluster/v1").hexdigest()


@dataclass(frozen=True)
class GraphNode:
    symbol_id: str
    name: str
    path: str
    source_range: SourceRange
    content_digest: str


@dataclass(frozen=True)
class GraphEdge:
    evidence_id: str
    source: str
    target: str
    kind: str
    path: str
    source_range: SourceRange
    content_digest: str


@dataclass(frozen=True)
class GraphGeneration:
    snapshot: SnapshotRef
    generation_id: str
    artifact_digest: str
    state: str
    coverage: Coverage
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    failed_files: tuple[tuple[str, str], ...]
    raw_artifact: bytes
    engine_identity: str = ENGINE_IDENTITY
    runtime_identity: str = RUNTIME_IDENTITY
    config_identity: str = CONFIG_IDENTITY
    model_routes_enabled: bool = False


def _range(value: dict, label: str) -> SourceRange:
    try:
        start, end = value["start"], value["end"]
        return SourceRange(start[0], start[1], end[0], end[1])
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise GenerationValidationError(f"{label} has invalid source locator") from error


def _native_range(value: dict, label: str) -> SourceRange:
    location = value.get("source_location")
    if not isinstance(location, str) or not location.startswith("L"):
        raise GenerationValidationError(f"{label} has invalid source locator")
    try:
        line = int(location[1:].split("-", 1)[0].split(":", 1)[0])
    except ValueError as error:
        raise GenerationValidationError(f"{label} has invalid source locator") from error
    return SourceRange(line, 1, line + 1, 1)


def native_graphify_payload(snapshot: SnapshotManifest, raw_artifact: bytes) -> bytes:
    try:
        native = json.loads(raw_artifact)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise GenerationValidationError("malformed native Graphify JSON") from error
    if not isinstance(native, dict):
        raise GenerationValidationError("malformed native Graphify JSON root")
    admitted = {entry.path for entry in snapshot.included}
    processed = set()
    nodes = []
    for value in native.get("nodes", []):
        if value.get("_origin") != "ast" or value.get("source_file") not in admitted:
            raise GenerationValidationError("native node is not deterministic admitted-source evidence")
        source_range = _native_range(value, "node")
        processed.add(value["source_file"])
        nodes.append({"id": value["id"], "name": value["label"], "path": value["source_file"], "start": [source_range.start_line, source_range.start_column], "end": [source_range.end_line, source_range.end_column]})
    edges = []
    for index, value in enumerate(native.get("edges", [])):
        if value.get("_origin") != "ast" or value.get("confidence") != "EXTRACTED" or value.get("source_file") not in admitted:
            raise GenerationValidationError("native edge is not deterministic admitted-source evidence")
        source_range = _native_range(value, "edge")
        processed.add(value["source_file"])
        edge_key = json.dumps([value.get("source"), value.get("target"), value.get("relation"), value.get("source_file"), value.get("source_location"), index], separators=(",", ":"))
        edges.append({"id": "edge-" + hashlib.sha256(edge_key.encode()).hexdigest(), "source": value["source"], "target": value["target"], "kind": value["relation"], "path": value["source_file"], "start": [source_range.start_line, source_range.start_column], "end": [source_range.end_line, source_range.end_column]})
    failed = [{"path": path, "reason": "unsupported_or_no_ast_evidence"} for path in sorted(admitted - processed)]
    canonical = {"source_snapshot_id": snapshot.snapshot_id, "evidence_grade": "deterministic_extraction", "processed_files": sorted(processed), "failed_files": failed, "nodes": nodes, "edges": edges}
    return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()


def normalize_generation(snapshot: SnapshotManifest, raw_artifact: bytes, *, expected_digest: str | None = None) -> GraphGeneration:
    digest = "sha256:" + hashlib.sha256(raw_artifact).hexdigest()
    if expected_digest is not None and digest != expected_digest:
        raise GenerationValidationError("artifact digest mismatch")
    try:
        raw = json.loads(raw_artifact)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise GenerationValidationError("malformed graph JSON") from error
    if not isinstance(raw, dict):
        raise GenerationValidationError("malformed graph JSON root")
    if raw.get("source_snapshot_id") != snapshot.snapshot_id:
        raise GenerationValidationError("source snapshot mismatch")
    if raw.get("evidence_grade") != "deterministic_extraction":
        raise GenerationValidationError("model-derived or generated evidence is disabled")
    admitted = {entry.path: entry.content_digest for entry in snapshot.included}
    processed = set(raw.get("processed_files", []))
    failed_items = raw.get("failed_files", [])
    failed = {item.get("path"): item.get("reason") for item in failed_items if isinstance(item, dict)}
    if processed & failed.keys() or processed | failed.keys() != admitted.keys():
        raise GenerationValidationError("unaccounted source files in extraction coverage")
    nodes = []
    for value in raw.get("nodes", []):
        if not all(field in value for field in ("id", "name", "path", "start", "end")) or value["path"] not in admitted:
            raise GenerationValidationError("node has missing or invalid source locator")
        nodes.append(GraphNode(value["id"], value["name"], value["path"], _range(value, "node"), admitted[value["path"]]))
    ids = {node.symbol_id for node in nodes}
    if len(ids) != len(nodes):
        raise GenerationValidationError("duplicate node identity")
    edges = []
    for value in raw.get("edges", []):
        if value.get("source") not in ids or value.get("target") not in ids:
            raise GenerationValidationError("dangling edge endpoint")
        if value.get("path") not in admitted:
            raise GenerationValidationError("edge has missing or invalid source locator")
        edges.append(GraphEdge(value["id"], value["source"], value["target"], value["kind"], value["path"], _range(value, "edge"), admitted[value["path"]]))
    state = "partial" if failed else "complete"
    coverage = Coverage("complete" if snapshot.inventory_complete else "partial", state, state, tuple(sorted(set(failed.values()))))
    snapshot_ref = SnapshotRef(snapshot.project_id, snapshot.repository_id, snapshot.snapshot_id, snapshot.commit, snapshot.content_manifest_digest)
    generation_id = "gen-" + hashlib.sha256((snapshot.snapshot_id + digest + "graphifyy:0.9.96").encode()).hexdigest()
    return GraphGeneration(snapshot_ref, generation_id, digest, state, coverage, tuple(sorted(nodes, key=lambda item: item.symbol_id)), tuple(sorted(edges, key=lambda item: item.evidence_id)), tuple(sorted(failed.items())), raw_artifact)


def extract_generation(snapshot: SnapshotManifest, source_dir: Path, staging_dir: Path, config: GraphifyConfig) -> GraphGeneration:
    run_graphify(source_dir, staging_dir, config)
    artifact_path = staging_dir.resolve() / "graphify-out" / "graph.json"
    try:
        raw_artifact = artifact_path.read_bytes()
    except OSError as error:
        raise GenerationValidationError("Graphify did not produce graph.json") from error
    canonical = native_graphify_payload(snapshot, raw_artifact)
    generation = normalize_generation(snapshot, canonical)
    native_digest = "sha256:" + hashlib.sha256(raw_artifact).hexdigest()
    identity = "\0".join((snapshot.snapshot_id, native_digest, ENGINE_IDENTITY, RUNTIME_IDENTITY, CONFIG_IDENTITY))
    generation_id = "gen-" + hashlib.sha256(identity.encode()).hexdigest()
    return GraphGeneration(
        generation.snapshot, generation_id, native_digest, generation.state,
        generation.coverage, generation.nodes, generation.edges, generation.failed_files,
        raw_artifact,
    )
