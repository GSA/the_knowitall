import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

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
    for name, data in (("metadata.json", _metadata(generation)), ("artifact.bin", generation.raw_artifact)):
        target = directory / name
        with target.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    _fsync_directory(directory)


def _read_generation(directory: Path) -> GraphGeneration:
    return _decode((directory / "metadata.json").read_bytes(), (directory / "artifact.bin").read_bytes())


def _generation_ref(generation: GraphGeneration) -> GenerationRef:
    return GenerationRef(generation.snapshot, generation.generation_id, generation.artifact_digest)


class PublicationStore:
    def __init__(self, root: Path):
        self.root = root
        for name in ("stages", "generations", "current"):
            (root / name).mkdir(parents=True, exist_ok=True)

    def _stage_path(self, stage_id: str) -> Path:
        return self.root / "stages" / _key(stage_id)

    def _generation_path(self, generation_id: str) -> Path:
        return self.root / "generations" / _key(generation_id)

    def _current_path(self, project_id: str, repository_id: str) -> Path:
        return self.root / "current" / _key(project_id, repository_id)

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

    def publish(self, staged: StagedGeneration, *, failpoint: str | None = None) -> PublicationReceipt:
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
                _fsync_directory(self.root / "generations")
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
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
        receipt_digest = "sha256:" + hashlib.sha256(pointer + generation.raw_artifact).hexdigest()
        return PublicationReceipt(reference, receipt_digest)

    def _validate(self, generation: GraphGeneration) -> None:
        digest = "sha256:" + hashlib.sha256(generation.raw_artifact).hexdigest()
        if digest != generation.artifact_digest:
            raise PublicationValidationError("artifact digest mismatch")
        try:
            validate_graph(generation)
        except ValueError as error:
            raise PublicationValidationError(str(error)) from error
        expected_state = "complete" if generation.coverage.inventory == "complete" and generation.coverage.extraction == "complete" else "partial"
        if generation.state != expected_state or generation.coverage.relevant_scope != expected_state:
            raise PublicationValidationError("coverage and generation state disagree")
        if generation.state == "partial" and not generation.coverage.limitations:
            raise PublicationValidationError("partial generation requires coverage limitations")
        identity = "\0".join((generation.snapshot.snapshot_id, generation.artifact_digest, generation.engine_identity, generation.runtime_identity, generation.config_identity))
        if generation.generation_id != "gen-" + hashlib.sha256(identity.encode()).hexdigest():
            raise PublicationValidationError("generation identity mismatch")

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
                        recovered.add(_read_generation(directory).generation_id)
                    except (OSError, ValueError, KeyError, json.JSONDecodeError):
                        continue
        return tuple(sorted(recovered))

    def resolve_exact(self, project_id: str, repository_id: str, snapshot_id: str, generation_id: str) -> GenerationRef:
        try:
            generation = _read_generation(self._generation_path(generation_id))
        except OSError as error:
            raise KeyError(generation_id) from error
        snapshot = generation.snapshot
        if (snapshot.project_id, snapshot.repository_id, snapshot.snapshot_id) != (project_id, repository_id, snapshot_id):
            raise KeyError(generation_id)
        return _generation_ref(generation)

    def resolve_current(self, project_id: str, repository_id: str) -> GenerationRef:
        try:
            value = json.loads(self._current_path(project_id, repository_id).read_bytes())
        except OSError as error:
            raise KeyError((project_id, repository_id)) from error
        return GenerationRef(SnapshotRef(**value["snapshot"]), value["generation_id"], value["artifact_digest"])

    def open_generation(self, reference: GenerationRef) -> GraphGeneration:
        try:
            generation = _read_generation(self._generation_path(reference.generation_id))
        except OSError as error:
            raise KeyError(reference.generation_id) from error
        if _generation_ref(generation) != reference:
            raise KeyError(reference.generation_id)
        return generation
