"""Synchronous local update orchestration using Graphify's own incremental route."""
import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from knowitall_graphify import extract_generation
from knowitall_graphify.adapter import _environment, _runtime_receipt, executable_digest
from knowitall_graphify.normalize import CONFIG_IDENTITY
from knowitall_publication import PublicationConflict
from knowitall_publication.durable import durable_directory
from knowitall_publication.store import _generation_ref

from . import checkpoint
from .ledger import decode_ref
from .models import UpdateConflict, UpdateInterrupted, UpdateValidationError


def runtime_identities(config):
    interpreter = config.executable.resolve(strict=True)
    if config.expected_executable_digest != executable_digest(interpreter):
        raise UpdateValidationError("interpreter digest mismatch")
    if not config.python_path:
        raise UpdateValidationError("trusted runtime root required")
    engine, runtime, digest = _runtime_receipt(config, interpreter, Path(config.python_path).resolve(strict=True), _environment())
    identity = "sha256:" + hashlib.sha256((CONFIG_IDENTITY + "\0" + digest).encode()).hexdigest()
    return engine, runtime, identity


class UpdateRunner:
    def __init__(self, ledger, config):
        self.ledger, self.config = ledger, config

    def submit(self, request_id, snapshot, *, expected_current):
        engine, runtime, config = runtime_identities(self.config)
        return self.ledger.submit(request_id, snapshot, expected_current=expected_current, engine_identity=engine, runtime_identity=runtime, config_identity=config)

    def resume(self, request_id, *, failpoint=None):
        ledger = self.ledger
        with ledger.store.locked():
            request = ledger.read_request(request_id)
            identities = tuple(request[name] for name in ("engine_identity", "runtime_identity", "config_identity"))
            if runtime_identities(self.config) != identities:
                raise UpdateConflict("runtime/config changed since acknowledgment")
            status = ledger.inspect(request_id)
            snapshot = ledger.load_snapshot(request_id)
            if status.phase == "published":
                generation = checkpoint.load(ledger, request_id)
                receipt = ledger.store.publish(ledger.store.stage(generation), expected_current=status.expected_current)
                if receipt != status.receipt:
                    raise UpdateValidationError("saved publication receipt mismatch")
                return status
            if not snapshot.inventory_complete:
                return ledger.set_status(request_id, phase="blocked", reasons=tuple((item.get("path", "."), item.get("reason", "inventory_failure")) for item in snapshot.failed) or ((".", "inventory_incomplete"),))
            path = ledger.request_path(request_id)
            try:
                if (path / "checkpoint").exists():
                    generation = checkpoint.load(ledger, request_id)
                else:
                    generation = self._extract(request_id, snapshot, identities)
                    if failpoint == "after_checkpoint":
                        raise UpdateInterrupted(failpoint)
                staged = ledger.store.stage(generation)
                ledger.set_status(request_id, phase="staged", generation=_generation_ref(generation))
                if failpoint == "after_stage":
                    raise UpdateInterrupted(failpoint)
                receipt = ledger.store.publish(staged, expected_current=status.expected_current, failpoint=failpoint)
                return ledger.set_status(request_id, phase="published", generation=receipt.generation, receipt=receipt)
            except UpdateInterrupted:
                raise
            except Exception as error:
                current = ledger.inspect(request_id)
                ledger.set_status(request_id, phase=current.phase, generation=current.generation, reasons=((".", type(error).__name__),))
                raise

    def _baseline(self, snapshot, identities, predecessor):
        candidates = []
        for path in (self.ledger.root / "requests").iterdir():
            if path.name.startswith(".") or not (path / "checkpoint").exists():
                continue
            try:
                request_id = json.loads((path / "request.json").read_bytes())["request_id"]
                saved = self.ledger.read_request(request_id)
                if tuple(saved[name] for name in ("engine_identity", "runtime_identity", "config_identity")) != identities:
                    continue
                generation = checkpoint.load(self.ledger, request_id)
                if (generation.snapshot.project_id, generation.snapshot.repository_id) != (snapshot.project_id, snapshot.repository_id):
                    continue
                if generation.snapshot.snapshot_id == snapshot.snapshot_id:
                    return request_id, generation, True
                if predecessor == _generation_ref(generation):
                    candidates.append((request_id, generation, False))
            except (ValueError, OSError, KeyError):
                continue
        return candidates[0] if candidates else None

    def _extract(self, request_id, snapshot, identities):
        ledger = self.ledger
        saved = ledger.read_request(request_id)
        predecessor = decode_ref(saved["expected_current"])
        try:
            current = ledger.store.resolve_current(snapshot.project_id, snapshot.repository_id)
        except KeyError:
            current = None
        if current != predecessor:
            raise PublicationConflict("current advanced before extraction")
        workspace = ledger.root / "workspace"
        # A single stable private path keeps Graphify's manifest paths valid.
        # It is rebuilt from committed companions after every interrupted attempt.
        shutil.rmtree(workspace, ignore_errors=True)
        durable_directory(workspace / "source")
        durable_directory(workspace / "output")
        baseline = self._baseline(snapshot, identities, predecessor)
        if baseline:
            baseline_id, generation, noop = baseline
            companions = workspace / "output" / "graphify-out"
            durable_directory(companions)
            for name in ("graph.json", "manifest.json"):
                shutil.copyfile(ledger.request_path(baseline_id) / "checkpoint" / name, companions / name)
            if noop:
                checkpoint.commit(ledger, request_id, workspace / "output", generation)
                return generation
        shutil.copytree(ledger.request_path(request_id) / "source", workspace / "source", dirs_exist_ok=True)
        ledger.set_status(request_id, phase="extracting")
        generation = extract_generation(snapshot, workspace / "source", workspace / "output", self.config)
        if (generation.engine_identity, generation.runtime_identity, generation.config_identity) != identities:
            raise UpdateValidationError("execution identity changed during extraction")
        checkpoint.commit(ledger, request_id, workspace / "output", generation)
        return generation
