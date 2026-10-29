"""Durable, atomically published storage for admitted SPUD bundles.

Retained bytes, normalized records and the admission receipt are staged in a
private temporary directory and published with a single rename, so an
interrupted admission never becomes queryable. Storage paths are derived from
hashes of the caller's identity, never from caller-supplied names.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .artifacts import RetainedArtifact, content_digest
from .records import ArtifactRecord, Locator, NormalizedBundle, SourceReference


FAILPOINTS = ("before_persist", "after_persist", "before_pointer")

_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600
_BUNDLE_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AdmissionConflict(ValueError):
    """A bundle identity was reused with different bytes, metadata, or selection."""


class AdmissionValidationError(ValueError):
    """Retained bytes or receipt metadata failed read-back verification."""


class AdmissionInterrupted(RuntimeError):
    """Admission stopped at a requested failpoint without publishing anything."""


@dataclass(frozen=True)
class AdmissionReceipt:
    project_id: str
    repository_id: str
    bundle_id: str
    receipt_digest: str
    reader_profile: str
    artifact_digests: tuple[tuple[str, str], ...]
    revision_binding: str
    artifact_completeness: str
    source_coverage: str
    limitations: tuple[tuple[str, str], ...]


def _key(*values: str) -> str:
    return hashlib.sha256("\0".join(values).encode("utf-8")).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_file(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def _metadata(bundle: NormalizedBundle) -> dict[str, object]:
    value = asdict(bundle)
    value["artifacts"] = [
        {"role": item.role, "path": item.path, "content_digest": item.content_digest}
        for item in bundle.artifacts
    ]
    return value


def _decode_record(value: dict[str, object]) -> ArtifactRecord:
    locator = Locator(**value["locator"])
    reference = value.get("source_reference")
    return ArtifactRecord(
        record_id=value["record_id"],
        kind=value["kind"],
        grade=value["grade"],
        name=value["name"],
        subject=value["subject"],
        object=value["object"],
        relation=value["relation"],
        text=value["text"],
        source_reference=SourceReference(**reference) if reference is not None else None,
        locator=locator,
        attribution=dict(value["attribution"]),
    )


def _decode_bundle(value: dict[str, object], payloads: dict[str, bytes]) -> NormalizedBundle:
    artifacts = []
    for item in value["artifacts"]:
        digest = item["content_digest"]
        if digest not in payloads:
            raise AdmissionValidationError(f"missing retained artifact {item['path']!r}")
        data = payloads[digest]
        if content_digest(data) != digest:
            raise AdmissionValidationError(f"retained artifact {item['path']!r} digest mismatch")
        artifacts.append(RetainedArtifact(item["role"], item["path"], digest, data))
    bound = value.get("bound_snapshot")
    return NormalizedBundle(
        project_id=value["project_id"],
        repository_id=value["repository_id"],
        bundle_id=value["bundle_id"],
        reader_profile=value["reader_profile"],
        supplied=dict(value["supplied"]),
        artifacts=tuple(artifacts),
        records=tuple(_decode_record(item) for item in value["records"]),
        limitations=tuple(tuple(item) for item in value["limitations"]),
        artifact_completeness=value["artifact_completeness"],
        source_coverage=value["source_coverage"],
        revision_binding=value["revision_binding"],
        bound_snapshot=dict(bound) if bound is not None else None,
    )


def _receipt(bundle: NormalizedBundle) -> AdmissionReceipt:
    digests = tuple(sorted((item.path, item.content_digest) for item in bundle.artifacts))
    identity = [
        bundle.project_id,
        bundle.repository_id,
        bundle.bundle_id,
        bundle.reader_profile,
        [list(item) for item in digests],
        [record.record_id for record in bundle.records],
        [list(item) for item in bundle.limitations],
        bundle.revision_binding,
        bundle.artifact_completeness,
        bundle.source_coverage,
        bundle.bound_snapshot,
    ]
    return AdmissionReceipt(
        project_id=bundle.project_id,
        repository_id=bundle.repository_id,
        bundle_id=bundle.bundle_id,
        receipt_digest="sha256:" + hashlib.sha256(_canonical(identity)).hexdigest(),
        reader_profile=bundle.reader_profile,
        artifact_digests=digests,
        revision_binding=bundle.revision_binding,
        artifact_completeness=bundle.artifact_completeness,
        source_coverage=bundle.source_coverage,
        limitations=bundle.limitations,
    )


class AdmissionStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=_DIRECTORY_MODE)
        for name in ("bundles", "index"):
            (self.root / name).mkdir(exist_ok=True, mode=_DIRECTORY_MODE)
        for path in (self.root, self.root / "bundles", self.root / "index"):
            if stat.S_IMODE(path.stat().st_mode) != _DIRECTORY_MODE:
                path.chmod(_DIRECTORY_MODE)

    def _bundle_path(self, project_id: str, repository_id: str, bundle_id: str) -> Path:
        return self.root / "bundles" / _key(project_id, repository_id, bundle_id)

    def _index_path(self, project_id: str, repository_id: str) -> Path:
        return self.root / "index" / _key(project_id, repository_id)

    def _pointer_path(self, project_id: str, repository_id: str, bundle_id: str) -> Path:
        return self._index_path(project_id, repository_id) / _key(bundle_id)

    def _stage(self, directory: Path, bundle: NormalizedBundle, receipt: AdmissionReceipt, failpoint: str | None) -> None:
        directory.mkdir(mode=_DIRECTORY_MODE)
        artifacts = directory / "artifacts"
        artifacts.mkdir(mode=_DIRECTORY_MODE)
        if failpoint == "before_persist":
            raise AdmissionInterrupted("before_persist")
        for item in bundle.artifacts:
            if content_digest(item.data) != item.content_digest:
                raise AdmissionValidationError(f"retained artifact {item.path!r} digest mismatch")
            target = artifacts / item.content_digest.removeprefix("sha256:")
            if not target.exists():
                _write_file(target, item.data)
        _fsync_directory(artifacts)
        _write_file(directory / "metadata.json", _canonical(_metadata(bundle)))
        if failpoint == "after_persist":
            raise AdmissionInterrupted("after_persist")
        _write_file(directory / "receipt.json", _canonical(asdict(receipt)))
        _fsync_directory(directory)

    def _read(self, directory: Path) -> tuple[NormalizedBundle, AdmissionReceipt]:
        if not directory.is_dir():
            raise KeyError(str(directory))
        try:
            metadata = json.loads((directory / "metadata.json").read_bytes())
            receipt_value = json.loads((directory / "receipt.json").read_bytes())
            payloads = {
                "sha256:" + path.name: path.read_bytes()
                for path in sorted((directory / "artifacts").iterdir())
            }
        except (OSError, json.JSONDecodeError) as error:
            raise AdmissionValidationError(f"retained bundle at {directory.name} cannot be read") from error
        bundle = _decode_bundle(metadata, payloads)
        receipt = AdmissionReceipt(
            project_id=receipt_value["project_id"],
            repository_id=receipt_value["repository_id"],
            bundle_id=receipt_value["bundle_id"],
            receipt_digest=receipt_value["receipt_digest"],
            reader_profile=receipt_value["reader_profile"],
            artifact_digests=tuple(tuple(item) for item in receipt_value["artifact_digests"]),
            revision_binding=receipt_value["revision_binding"],
            artifact_completeness=receipt_value["artifact_completeness"],
            source_coverage=receipt_value["source_coverage"],
            limitations=tuple(tuple(item) for item in receipt_value["limitations"]),
        )
        if receipt != _receipt(bundle):
            raise AdmissionValidationError(f"receipt does not match retained bundle {receipt.bundle_id!r}")
        return bundle, receipt

    def _compare(self, directory: Path, bundle: NormalizedBundle) -> None:
        existing, _receipt_value = self._read(directory)
        if tuple(sorted((item.path, item.content_digest) for item in existing.artifacts)) != tuple(
            sorted((item.path, item.content_digest) for item in bundle.artifacts)
        ):
            raise AdmissionConflict(
                f"bundle {bundle.bundle_id!r} was admitted with different retained bytes or artifact selection"
            )
        if existing != bundle:
            raise AdmissionConflict(f"bundle {bundle.bundle_id!r} was admitted with different retained metadata")

    def _publish_pointer(self, bundle: NormalizedBundle) -> None:
        index = self._index_path(bundle.project_id, bundle.repository_id)
        index.mkdir(exist_ok=True, mode=_DIRECTORY_MODE)
        pointer = self._pointer_path(bundle.project_id, bundle.repository_id, bundle.bundle_id)
        payload = _canonical(
            {
                "project_id": bundle.project_id,
                "repository_id": bundle.repository_id,
                "bundle_id": bundle.bundle_id,
                "bundle_key": _key(bundle.project_id, bundle.repository_id, bundle.bundle_id),
            }
        )
        descriptor, name = tempfile.mkstemp(prefix=".pointer-", dir=index)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, pointer)
        finally:
            temporary.unlink(missing_ok=True)
        _fsync_directory(index)

    def admit(self, bundle: NormalizedBundle, *, failpoint: str | None = None) -> AdmissionReceipt:
        if failpoint is not None and failpoint not in FAILPOINTS:
            raise AdmissionValidationError(f"unsupported failpoint: {failpoint!r}")
        receipt = _receipt(bundle)
        destination = self._bundle_path(bundle.project_id, bundle.repository_id, bundle.bundle_id)
        if destination.exists():
            self._compare(destination, bundle)
            if failpoint == "before_pointer":
                raise AdmissionInterrupted("before_pointer")
            self._publish_pointer(bundle)
            return receipt
        temporary = Path(tempfile.mkdtemp(prefix=".admit-", dir=self.root / "bundles"))
        try:
            self._stage(temporary / "bundle", bundle, receipt, failpoint)
            try:
                os.rename(temporary / "bundle", destination)
            except OSError as error:
                if error.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
                self._compare(destination, bundle)
            _fsync_directory(self.root / "bundles")
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        if failpoint == "before_pointer":
            raise AdmissionInterrupted("before_pointer")
        self._publish_pointer(bundle)
        return receipt

    def _pointer_key(self, project_id: str, repository_id: str, bundle_id: str) -> str:
        pointer = self._pointer_path(project_id, repository_id, bundle_id)
        try:
            value = json.loads(pointer.read_bytes())
        except (OSError, json.JSONDecodeError) as error:
            raise KeyError((project_id, repository_id, bundle_id)) from error
        key = value.get("bundle_key")
        identity = (value.get("project_id"), value.get("repository_id"), value.get("bundle_id"))
        if identity != (project_id, repository_id, bundle_id):
            raise KeyError((project_id, repository_id, bundle_id))
        if not isinstance(key, str) or not _BUNDLE_KEY_PATTERN.match(key):
            raise KeyError((project_id, repository_id, bundle_id))
        return key

    def open_bundle(self, project_id: str, repository_id: str, bundle_id: str) -> tuple[NormalizedBundle, AdmissionReceipt]:
        key = self._pointer_key(project_id, repository_id, bundle_id)
        bundle, receipt = self._read(self.root / "bundles" / key)
        if (bundle.project_id, bundle.repository_id, bundle.bundle_id) != (project_id, repository_id, bundle_id):
            raise KeyError((project_id, repository_id, bundle_id))
        return bundle, receipt

    def list_bundles(self, project_id: str, repository_id: str) -> tuple[str, ...]:
        index = self._index_path(project_id, repository_id)
        if not index.is_dir():
            return ()
        found = []
        for pointer in index.iterdir():
            if pointer.name.startswith("."):
                continue
            try:
                found.append(json.loads(pointer.read_bytes())["bundle_id"])
            except (OSError, KeyError, json.JSONDecodeError):
                continue
        return tuple(sorted(found))

    def _pointers(self) -> tuple[tuple[tuple[str, str, str], str], ...]:
        """Every readable index pointer as ((project, repository, bundle), bundle_key)."""
        index_root = self.root / "index"
        if not index_root.is_dir():
            return ()
        found = []
        for index in index_root.iterdir():
            if not index.is_dir():
                continue
            for pointer in index.iterdir():
                if pointer.name.startswith("."):
                    continue
                try:
                    value = json.loads(pointer.read_bytes())
                    identity = (value["project_id"], value["repository_id"], value["bundle_id"])
                    key = value["bundle_key"]
                except (OSError, KeyError, json.JSONDecodeError):
                    continue
                if isinstance(key, str) and _BUNDLE_KEY_PATTERN.match(key):
                    found.append((identity, key))
        return tuple(sorted(found))

    def damaged_bundles(self) -> tuple[tuple[str, str, str], ...]:
        """Identities of referenced bundles whose retained evidence cannot be read.

        Damage is reported, never repaired: an operator decides whether to
        inspect the retained directory or discard it with `discard_damaged`.
        """
        damaged = []
        for identity, key in self._pointers():
            try:
                self._read(self.root / "bundles" / key)
            except (KeyError, AdmissionValidationError):
                damaged.append(identity)
        return tuple(sorted(damaged))

    def discard_damaged(self, project_id: str, repository_id: str, bundle_id: str) -> None:
        """Remove a damaged bundle and its pointer so the id can be re-admitted."""
        key = self._pointer_key(project_id, repository_id, bundle_id)
        directory = self.root / "bundles" / key
        try:
            self._read(directory)
        except (KeyError, AdmissionValidationError):
            pass
        else:
            raise AdmissionConflict(f"bundle {bundle_id!r} is readable and will not be discarded")
        shutil.rmtree(directory, ignore_errors=True)
        self._pointer_path(project_id, repository_id, bundle_id).unlink(missing_ok=True)
        _fsync_directory(self.root / "bundles")
        _fsync_directory(self._index_path(project_id, repository_id))

    def recover(self) -> tuple[str, ...]:
        bundles = self.root / "bundles"
        for temporary in bundles.glob(".admit-*"):
            shutil.rmtree(temporary, ignore_errors=True)
        for index in (self.root / "index").iterdir():
            if index.is_dir():
                for temporary in index.glob(".pointer-*"):
                    temporary.unlink(missing_ok=True)
        referenced = {key: identity[2] for identity, key in self._pointers()}
        recovered = set()
        for directory in bundles.iterdir():
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            if directory.name not in referenced:
                shutil.rmtree(directory, ignore_errors=True)
                continue
            try:
                self._read(directory)
            except (KeyError, AdmissionValidationError):
                continue  # damaged: reported by damaged_bundles(), never repaired here
            recovered.add(referenced[directory.name])
        return tuple(sorted(recovered))
