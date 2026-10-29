"""Durable requests retain admitted source, never a moving checkout reference."""
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from knowitall_contract import GenerationRef, SnapshotRef
from knowitall_publication import PublicationReceipt, PublicationStore
from knowitall_publication.durable import atomic_write, durable_directory, fsync_directory
from knowitall_snapshot import SnapshotManifest
from knowitall_snapshot.inventory import InventoryEntry, safe_path

from .models import UpdateConflict, UpdateStatus, UpdateValidationError


def encode(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def reference(snapshot: SnapshotManifest) -> SnapshotRef:
    return SnapshotRef(snapshot.project_id, snapshot.repository_id, snapshot.snapshot_id, snapshot.commit, snapshot.content_manifest_digest)


def decode_ref(value):
    if value is None:
        return None
    return GenerationRef(SnapshotRef(**value["snapshot"]), value["generation_id"], value["artifact_digest"])


def validate_snapshot(snapshot):
    paths = set()
    for entry in snapshot.included:
        safe_path(entry.path)
        if entry.path in paths or digest(entry.data) != entry.content_digest:
            raise UpdateValidationError("invalid admitted source bytes or duplicate path")
        paths.add(entry.path)
    content = b"".join(entry.path.encode() + b"\0" + entry.content_digest.encode() + b"\0" for entry in snapshot.included)
    if digest(content) != snapshot.content_manifest_digest:
        raise UpdateValidationError("content manifest digest mismatch")
    reference(snapshot)


class UpdateLedger:
    def __init__(self, root: Path, store: PublicationStore):
        self.root, self.store = root, store
        durable_directory(root)
        durable_directory(root / "requests")

    def request_path(self, request_id: str) -> Path:
        if not isinstance(request_id, str) or not request_id:
            raise UpdateValidationError("request identity must be nonempty")
        return self.root / "requests" / hashlib.sha256(request_id.encode()).hexdigest()

    def submit(self, request_id: str, snapshot: SnapshotManifest, *, expected_current: GenerationRef | None, engine_identity: str, runtime_identity: str, config_identity: str) -> UpdateStatus:
        validate_snapshot(snapshot)
        if any(not isinstance(value, str) or not value for value in (engine_identity, runtime_identity, config_identity)):
            raise UpdateValidationError("extraction identities must be nonempty")
        if expected_current and (expected_current.snapshot.project_id, expected_current.snapshot.repository_id) != (snapshot.project_id, snapshot.repository_id):
            raise UpdateConflict("predecessor belongs to another repository")
        manifest = json.loads(snapshot.canonical())
        request = {"version": 1, "request_id": request_id, "manifest": manifest, "expected_current": asdict(expected_current) if expected_current else None, "engine_identity": engine_identity, "runtime_identity": runtime_identity, "config_identity": config_identity}
        data = encode(request)
        path = self.request_path(request_id)
        with self.store.locked():
            if path.exists():
                if self.read_request(request_id) != request:
                    raise UpdateConflict("idempotency key has different immutable inputs")
                self.load_snapshot(request_id)
                return self.inspect(request_id)
            temporary = Path(tempfile.mkdtemp(prefix=".request-", dir=path.parent))
            try:
                durable_directory(temporary / "source")
                for entry in snapshot.included:
                    target = temporary / "source" / entry.path
                    durable_directory(target.parent)
                    atomic_write(target, entry.data)
                atomic_write(temporary / "request.json", data)
                atomic_write(temporary / "request.sha256", digest(data).encode())
                atomic_write(temporary / "status.json", encode({"phase": "requested", "generation": None, "receipt": None, "reasons": []}))
                fsync_directory(temporary)
                os.rename(temporary, path)
                fsync_directory(path.parent)
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
            return self.inspect(request_id)

    def read_request(self, request_id: str):
        path = self.request_path(request_id)
        try:
            data = (path / "request.json").read_bytes()
            if digest(data).encode() != (path / "request.sha256").read_bytes():
                raise UpdateValidationError("saved request digest mismatch")
            value = json.loads(data)
            if value["version"] != 1 or value["request_id"] != request_id:
                raise UpdateValidationError("unsupported or mismatched request")
            return value
        except (ValueError, TypeError, KeyError) as error:
            raise UpdateValidationError("invalid saved request") from error

    def load_snapshot(self, request_id: str) -> SnapshotManifest:
        try:
            value = dict(self.read_request(request_id)["manifest"])
            entries = []
            for item in value["included"]:
                safe_path(item["path"])
                path = self.request_path(request_id) / "source" / item["path"]
                if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
                    raise UpdateValidationError("saved source must not contain symlinks")
                entries.append(InventoryEntry(**item, data=path.read_bytes()))
            value["included"] = tuple(entries)
            value["excluded"] = tuple(value["excluded"])
            value["failed"] = tuple(value["failed"])
            snapshot = SnapshotManifest(**value)
            validate_snapshot(snapshot)
            return snapshot
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise UpdateValidationError("invalid saved snapshot") from error

    def inspect(self, request_id: str) -> UpdateStatus:
        request = self.read_request(request_id)
        try:
            value = json.loads((self.request_path(request_id) / "status.json").read_bytes())
            if value["phase"] not in {"requested", "extracting", "staged", "published", "blocked"}:
                raise ValueError("invalid update phase")
            receipt = value["receipt"]
            return UpdateStatus(request_id, value["phase"], reference(self.load_snapshot(request_id)), decode_ref(request["expected_current"]), decode_ref(value["generation"]), PublicationReceipt(decode_ref(receipt["generation"]), receipt["receipt_digest"]) if receipt else None, tuple(tuple(item) for item in value["reasons"]))
        except (ValueError, KeyError, TypeError) as error:
            raise UpdateValidationError("invalid saved status") from error

    def set_status(self, request_id: str, *, phase: str, generation=None, receipt=None, reasons=()) -> UpdateStatus:
        with self.store.locked():
            atomic_write(self.request_path(request_id) / "status.json", encode({"phase": phase, "generation": asdict(generation) if generation else None, "receipt": asdict(receipt) if receipt else None, "reasons": reasons}))
            return self.inspect(request_id)
