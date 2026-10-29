"""Commit extraction companions together; never resume from half-written output."""
import json
import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from knowitall_graphify import normalize_generation
from knowitall_graphify.normalize import native_graphify_payload
from knowitall_publication.durable import atomic_write, fsync_directory
from knowitall_publication.store import _metadata, _read_generation, _write_generation

from .ledger import digest, encode
from .models import UpdateValidationError


def reconstruct(snapshot, raw, identities):
    value = json.loads(raw)
    canonical = raw if "source_snapshot_id" in value else native_graphify_payload(snapshot, raw)
    generation = normalize_generation(snapshot, canonical)
    from knowitall_graphify.normalize import expected_generation_id
    rebuilt = replace(generation, artifact_digest=digest(raw), raw_artifact=raw, engine_identity=identities[0], runtime_identity=identities[1], config_identity=identities[2])
    return replace(rebuilt, generation_id=expected_generation_id(rebuilt))


def commit(ledger, request_id: str, output_dir: Path, generation) -> None:
    with ledger.store.locked():
        snapshot = ledger.load_snapshot(request_id)
        rebuilt = reconstruct(snapshot, generation.raw_artifact, (generation.engine_identity, generation.runtime_identity, generation.config_identity))
        if rebuilt != generation:
            raise UpdateValidationError("generation disagrees with saved snapshot and artifact")
        ledger.store._validate(generation)
        parent = ledger.request_path(request_id)
        destination = parent / "checkpoint"
        if destination.exists():
            if load(ledger, request_id) != generation:
                raise UpdateValidationError("checkpoint already exists with different bytes")
            return
        temporary = Path(tempfile.mkdtemp(prefix=".checkpoint-", dir=parent))
        try:
            raw = (output_dir / "graphify-out" / "graph.json").read_bytes()
            manifest = (output_dir / "graphify-out" / "manifest.json").read_bytes()
            if raw != generation.raw_artifact or not isinstance(json.loads(manifest), dict):
                raise UpdateValidationError("invalid extraction companions")
            _write_generation(temporary / "generation", generation)
            atomic_write(temporary / "graph.json", raw)
            atomic_write(temporary / "manifest.json", manifest)
            atomic_write(temporary / "digests.json", encode({"graph.json": digest(raw), "manifest.json": digest(manifest), "metadata": digest(_metadata(generation))}))
            fsync_directory(temporary)
            os.rename(temporary, destination)
            fsync_directory(parent)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)


def load(ledger, request_id: str):
    try:
        path = ledger.request_path(request_id) / "checkpoint"
        hashes = json.loads((path / "digests.json").read_bytes())
        for name in ("graph.json", "manifest.json"):
            if digest((path / name).read_bytes()) != hashes[name]:
                raise UpdateValidationError("extraction companion digest mismatch")
        generation = _read_generation(path / "generation")
        if digest(_metadata(generation)) != hashes["metadata"]:
            raise UpdateValidationError("checkpoint metadata digest mismatch")
        rebuilt = reconstruct(ledger.load_snapshot(request_id), (path / "graph.json").read_bytes(), (generation.engine_identity, generation.runtime_identity, generation.config_identity))
        if rebuilt != generation:
            raise UpdateValidationError("checkpoint provenance mismatch")
        ledger.store._validate(generation)
        return generation
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise UpdateValidationError("invalid extraction checkpoint") from error
