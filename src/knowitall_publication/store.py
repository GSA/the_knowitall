import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from functools import wraps

from .durable import atomic_write, durable_directory, locked

_UNSPECIFIED = object()


def _serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.locked():
            return method(self, *args, **kwargs)
    return wrapped

from knowitall_contract import Coverage, GenerationRef, SnapshotRef, SourceRange
from knowitall_graphify import GraphEdge, GraphGeneration, GraphNode
from knowitall_snapshot import SnapshotManifest
from knowitall_graphify import validate_generation as validate_graph


class PublicationConflict(ValueError):
    pass


class PublicationValidationError(ValueError):
    pass


class PublicationInterrupted(RuntimeError):
    pass


@dataclass(frozen=True)
class StagedGeneration:
    stage_id: str
    generation_id: str


@dataclass(frozen=True)
class PublicationReceipt:
    generation: GenerationRef
    receipt_digest: str


def _key(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode()).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _metadata(generation: GraphGeneration) -> bytes:
    value = asdict(generation)
    value.pop("raw_artifact")
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _decode(metadata: bytes, artifact: bytes) -> GraphGeneration:
    value = json.loads(metadata)
    snapshot_value = value["snapshot"]
    snapshot = SnapshotRef(**snapshot_value)
    coverage_value = value["coverage"]
    coverage = Coverage(coverage_value["inventory"], coverage_value["extraction"], coverage_value["relevant_scope"], tuple(coverage_value["limitations"]))
    nodes = tuple(GraphNode(item["symbol_id"], item["name"], item["path"], SourceRange(**item["source_range"]), item["content_digest"]) for item in value["nodes"])
    edges = tuple(GraphEdge(item["evidence_id"], item["source"], item["target"], item["kind"], item["path"], SourceRange(**item["source_range"]), item["content_digest"]) for item in value["edges"])
    return GraphGeneration(snapshot, value["generation_id"], value["artifact_digest"], value["state"], coverage, nodes, edges, tuple(tuple(item) for item in value["failed_files"]), artifact, value["engine_identity"], value["runtime_identity"], value["config_identity"], value["model_routes_enabled"], tuple(tuple(item) for item in value.get("inventory_failures", ())), tuple(tuple(item) for item in value.get("exclusions", ())))


def _write_generation(directory: Path, generation: GraphGeneration) -> None:
    directory.mkdir(parents=True)
    metadata = _metadata(generation)
    for name, data in (("metadata.json", metadata), ("artifact.bin", generation.raw_artifact), ("metadata.sha256", hashlib.sha256(metadata).hexdigest().encode())):
        target = directory / name
        with target.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    _fsync_directory(directory)


def _read_generation(directory: Path) -> GraphGeneration:
    try:
        metadata = (directory / "metadata.json").read_bytes()
        if hashlib.sha256(metadata).hexdigest().encode() != (directory / "metadata.sha256").read_bytes():
            raise PublicationValidationError("persisted metadata digest mismatch")
        return _decode(metadata, (directory / "artifact.bin").read_bytes())
    except (ValueError, KeyError, TypeError, IndexError) as error:
        raise PublicationValidationError("invalid persisted generation") from error


def _generation_ref(generation: GraphGeneration) -> GenerationRef:
    return GenerationRef(generation.snapshot, generation.generation_id, generation.artifact_digest)


class PublicationStore:
    def __init__(self, root: Path):
        self.root = root
        durable_directory(root)
        for name in ("stages", "generations", "current", "receipts", "intents"):
            durable_directory(root / name)

    def locked(self):
        return locked(self.root)

    def _stage_path(self, stage_id: str) -> Path:
        return self.root / "stages" / _key(stage_id)

    def _generation_path(self, generation_id: str) -> Path:
        return self.root / "generations" / _key(generation_id)

    def _current_path(self, project_id: str, repository_id: str) -> Path:
        return self.root / "current" / _key(project_id, repository_id)

    @_serialized
    def stage(self, generation: GraphGeneration) -> StagedGeneration:
        stage_id = generation.generation_id
        path = self._stage_path(stage_id)
        metadata = _metadata(generation)
        if path.exists():
            existing = _read_generation(path)
            if _metadata(existing) != metadata or existing.raw_artifact != generation.raw_artifact:
                raise PublicationConflict("generation identity has different staged bytes")
            return StagedGeneration(stage_id, generation.generation_id)
        published = self._generation_path(generation.generation_id)
        if published.exists():
            existing = _read_generation(published)
            if _metadata(existing) != metadata or existing.raw_artifact != generation.raw_artifact:
                raise PublicationConflict("generation identity has different published bytes")
        temporary = Path(tempfile.mkdtemp(prefix=".stage-", dir=self.root / "stages"))
        try:
            _write_generation(temporary / "generation", generation)
            try:
                os.rename(temporary / "generation", path)
            except FileExistsError:
                existing = _read_generation(path)
                if _metadata(existing) != metadata or existing.raw_artifact != generation.raw_artifact:
                    raise PublicationConflict("generation identity raced with different staged bytes")
            _fsync_directory(self.root / "stages")
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        return StagedGeneration(stage_id, generation.generation_id)

    def resume(self, stage_id: str) -> StagedGeneration:
        generation = _read_generation(self._stage_path(stage_id))
        return StagedGeneration(stage_id, generation.generation_id)

    @_serialized
    def publish(self, staged: StagedGeneration, *, expected_current=_UNSPECIFIED, failpoint: str | None = None) -> PublicationReceipt:
        stage_path = self._stage_path(staged.stage_id)
        try:
            generation = _read_generation(stage_path)
        except OSError as error:
            raise KeyError(staged.stage_id) from error
        if staged.generation_id != generation.generation_id or staged.stage_id != generation.generation_id:
            raise PublicationValidationError("staged handle identity mismatch")
        if failpoint == "before_validation":
            raise PublicationInterrupted(failpoint)
        self._validate(generation)
        if failpoint == "after_validation":
            raise PublicationInterrupted(failpoint)
        reference = _generation_ref(generation)
        pointer = (json.dumps(asdict(reference), sort_keys=True, separators=(",", ":")) + "\n").encode()
        receipt = PublicationReceipt(reference, "sha256:" + hashlib.sha256(pointer + generation.raw_artifact).hexdigest())
        receipt_path = self.root / "receipts" / _key(generation.generation_id)
        if receipt_path.exists():
            if receipt_path.read_bytes() != pointer:
                raise PublicationValidationError("publication receipt mismatch")
            self.open_generation(reference)
            return receipt
        try:
            current = self.resolve_current(generation.snapshot.project_id, generation.snapshot.repository_id)
        except KeyError:
            current = None
        if current is not None:
            prior_intent = self.root / "intents" / _key(current.generation_id)
            prior_receipt = self.root / "receipts" / _key(current.generation_id)
            if prior_intent.exists() and not prior_receipt.exists():
                value = json.loads(prior_intent.read_bytes())
                if value["target"] != asdict(current):
                    raise PublicationValidationError("publication intent target mismatch")
                _fsync_directory(self.root / "current")
                atomic_write(prior_receipt, (json.dumps(asdict(current), sort_keys=True, separators=(",", ":")) + "\n").encode())
        intent_path = self.root / "intents" / _key(generation.generation_id)
        if current == reference and intent_path.exists():
            _fsync_directory(self.root / "current")
            atomic_write(receipt_path, pointer)
            return receipt
        if expected_current is not _UNSPECIFIED and current != expected_current:
            raise PublicationConflict("current does not match expected predecessor")
        intent = json.dumps({"target": asdict(reference), "predecessor": asdict(current) if current else None}, sort_keys=True).encode()
        if intent_path.exists() and intent_path.read_bytes() != intent:
            # Completed/selected generations returned above. Only an explicitly
            # validated predecessor permits rebinding an unpublished intent.
            if expected_current is _UNSPECIFIED:
                raise PublicationConflict("publication intent predecessor changed")
        atomic_write(intent_path, intent)
        destination = self._generation_path(generation.generation_id)
        if destination.exists():
            existing = _read_generation(destination)
            if existing != generation:
                raise PublicationConflict("generation identity has different published bytes")
        else:
            temporary = Path(tempfile.mkdtemp(prefix=".publish-", dir=self.root / "generations"))
            try:
                _write_generation(temporary / "generation", generation)
                try:
                    os.rename(temporary / "generation", destination)
                except FileExistsError:
                    existing = _read_generation(destination)
                    if existing != generation:
                        raise PublicationConflict("generation identity raced with different published bytes")
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
        # An existing destination may be a rename left by an interrupted publisher.
        # Persist it before selecting or acknowledging the generation on retry too.
        _fsync_directory(self.root / "generations")
        if failpoint == "before_current_replace":
            raise PublicationInterrupted(failpoint)
        reference = _generation_ref(generation)
        pointer = (json.dumps(asdict(reference), sort_keys=True, separators=(",", ":")) + "\n").encode()
        current_path = self._current_path(generation.snapshot.project_id, generation.snapshot.repository_id)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".pointer-", dir=self.root / "current")
        temporary_pointer = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(pointer)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_pointer, current_path)
        finally:
            temporary_pointer.unlink(missing_ok=True)
        _fsync_directory(self.root / "current")
        if failpoint == "after_current_replace":
            raise PublicationInterrupted(failpoint)
        atomic_write(receipt_path, pointer)
        return receipt

    def _validate(self, generation: GraphGeneration) -> None:
        digest = "sha256:" + hashlib.sha256(generation.raw_artifact).hexdigest()
        if digest != generation.artifact_digest:
            raise PublicationValidationError("artifact digest mismatch")
        if generation.model_routes_enabled:
            raise PublicationValidationError("model routes are disabled")
        try:
            validate_graph(generation)
            raw = json.loads(generation.raw_artifact)
            canonical = "source_snapshot_id" in raw
            if canonical and raw["source_snapshot_id"] != generation.snapshot.snapshot_id:
                raise ValueError("raw snapshot mismatch")
            native_nodes = raw.get("nodes", [])
            expected = sorted((item["id"], item["name"] if canonical else item["label"], item["path"] if canonical else item["source_file"]) for item in native_nodes)
            actual = sorted((node.symbol_id, node.name, node.path) for node in generation.nodes)
            if expected != actual:
                raise ValueError("normalized nodes disagree with raw artifact")
            def locator(item):
                if canonical:
                    return SourceRange(*item["start"], *item["end"])
                from knowitall_graphify.normalize import _native_range
                if item.get("_origin") != "ast":
                    raise ValueError("native evidence is not AST-bound")
                return _native_range(item, "evidence")

            nodes = {node.symbol_id: node for node in generation.nodes}
            for item in native_nodes:
                if nodes[item["id"]].source_range != locator(item):
                    raise ValueError("normalized node locator disagrees with raw artifact")
            expected_edges = []
            for index, item in enumerate(raw.get("edges", [])):
                if canonical:
                    evidence_id = item["id"]
                else:
                    if item.get("confidence") != "EXTRACTED":
                        raise ValueError("native edge is not extracted evidence")
                    edge_key = json.dumps([item.get("source"), item.get("target"), item.get("relation"), item.get("source_file"), item.get("source_location"), index], separators=(",", ":"))
                    evidence_id = "edge-" + hashlib.sha256(edge_key.encode()).hexdigest()
                expected_edges.append((evidence_id, item["source"], item["target"], item["kind"] if canonical else item["relation"], item["path"] if canonical else item["source_file"], locator(item)))
            actual_edges = [(edge.evidence_id, edge.source, edge.target, edge.kind, edge.path, edge.source_range) for edge in generation.edges]
            if sorted(expected_edges) != sorted(actual_edges):
                raise ValueError("normalized edges disagree with raw artifact")
            validate_graph(generation)
        except (ValueError, KeyError, TypeError) as error:
            raise PublicationValidationError(str(error)) from error
        expected_state = "complete" if generation.coverage.inventory == "complete" and generation.coverage.extraction == "complete" else "partial"
        if generation.state != expected_state or generation.coverage.relevant_scope != expected_state:
            raise PublicationValidationError("coverage and generation state disagree")
        if generation.state == "partial" and not generation.coverage.limitations:
            raise PublicationValidationError("partial generation requires coverage limitations")
        identity = "\0".join((generation.snapshot.snapshot_id, generation.artifact_digest, generation.engine_identity, generation.runtime_identity, generation.config_identity))
        if generation.generation_id != "gen-" + hashlib.sha256(identity.encode()).hexdigest():
            raise PublicationValidationError("generation identity mismatch")

    @_serialized
    def recover(self) -> tuple[str, ...]:
        recovered = set()
        for parent in (self.root / "stages", self.root / "generations", self.root / "current"):
            for temporary in parent.glob(".*-"):
                shutil.rmtree(temporary, ignore_errors=True)
            for temporary in parent.glob(".stage-*"):
                shutil.rmtree(temporary, ignore_errors=True)
            for temporary in parent.glob(".publish-*"):
                shutil.rmtree(temporary, ignore_errors=True)
            for temporary in parent.glob(".pointer-*"):
                temporary.unlink(missing_ok=True)
        for parent in (self.root / "stages", self.root / "generations"):
            for directory in parent.iterdir():
                if directory.is_dir() and not directory.name.startswith("."):
                    try:
                        generation = _read_generation(directory)
                        self._validate(generation)
                        recovered.add(generation.generation_id)
                    except (OSError, ValueError, KeyError, json.JSONDecodeError):
                        continue
        return tuple(sorted(recovered))

    def resolve_exact(self, project_id: str, repository_id: str, snapshot_id: str, generation_id: str) -> GenerationRef:
        try:
            generation = _read_generation(self._generation_path(generation_id))
        except OSError as error:
            raise KeyError(generation_id) from error
        self._validate(generation)
        snapshot = generation.snapshot
        if (snapshot.project_id, snapshot.repository_id, snapshot.snapshot_id) != (project_id, repository_id, snapshot_id):
            raise KeyError(generation_id)
        return _generation_ref(generation)

    def resolve_current(self, project_id: str, repository_id: str) -> GenerationRef:
        try:
            value = json.loads(self._current_path(project_id, repository_id).read_bytes())
            reference = GenerationRef(SnapshotRef(**value["snapshot"]), value["generation_id"], value["artifact_digest"])
        except OSError as error:
            raise KeyError((project_id, repository_id)) from error
        except (ValueError, KeyError, TypeError) as error:
            raise PublicationValidationError("invalid current pointer") from error
        if (reference.snapshot.project_id, reference.snapshot.repository_id) != (project_id, repository_id):
            raise PublicationValidationError("current pointer repository mismatch")
        try:
            self.open_generation(reference)
        except KeyError as error:
            raise PublicationValidationError("current pointer references missing generation evidence") from error
        return reference

    def open_generation(self, reference: GenerationRef) -> GraphGeneration:
        try:
            generation = _read_generation(self._generation_path(reference.generation_id))
        except OSError as error:
            raise KeyError(reference.generation_id) from error
        self._validate(generation)
        if _generation_ref(generation) != reference:
            raise PublicationValidationError("generation reference mismatch")
        return generation
