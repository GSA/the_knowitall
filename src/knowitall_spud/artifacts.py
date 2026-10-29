"""Safe retention of already supplied SPUD bundle artifacts.

Nothing here runs a producer, resolves outside the supplied bundle root,
extracts an archive, or interprets artifact content as instructions.
"""

from __future__ import annotations

import hashlib
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover - annotation only; BundleLimits lives in descriptor
    from .descriptor import BundleLimits


DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class ArtifactError(ValueError):
    """A supplied bundle path, artifact size, or artifact digest is unacceptable."""


class _Selection(Protocol):
    role: str
    path: str


@dataclass(frozen=True)
class RetainedArtifact:
    role: str
    path: str
    content_digest: str
    data: bytes


def content_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def is_digest(value: object) -> bool:
    return isinstance(value, str) and DIGEST_PATTERN.match(value) is not None


def safe_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactError(f"unsafe bundle path: {value!r}")
    if "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise ArtifactError(f"unsafe bundle path: {value!r}")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ArtifactError(f"unsafe bundle path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ArtifactError(f"unsafe bundle path: {value!r}")
    return str(path)


def _regular_file(bundle_root: Path, relative: str) -> Path:
    current = bundle_root
    if current.is_symlink():
        raise ArtifactError(f"bundle root is not a regular directory: {relative!r}")
    parts = relative.split("/")
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise ArtifactError(f"bundle artifact is not a regular file: {relative!r}")
    target = current / parts[-1]
    if target.is_symlink():
        raise ArtifactError(f"bundle artifact is not a regular file: {relative!r}")
    try:
        mode = target.lstat().st_mode
    except OSError as error:
        raise ArtifactError(f"bundle artifact is unreadable: {relative!r}") from error
    if not stat.S_ISREG(mode):
        raise ArtifactError(f"bundle artifact is not a regular file: {relative!r}")
    return target


def read_bundle(
    bundle_root: Path,
    selected: Sequence[_Selection],
    limits: BundleLimits,
    expected_digests: Mapping[str, str],
) -> tuple[RetainedArtifact, ...]:
    ordered = sorted(selected, key=lambda item: (item.role, item.path))
    if len(ordered) > limits.max_files:
        raise ArtifactError(f"selection of {len(ordered)} artifacts exceeds file limit {limits.max_files}")
    seen: set[str] = set()
    for key, value in expected_digests.items():
        if not is_digest(value):
            raise ArtifactError(f"expected digest for {key!r} is not a sha256 digest")
    retained: list[RetainedArtifact] = []
    total = 0
    for item in ordered:
        relative = safe_relative_path(item.path)
        if relative in seen:
            raise ArtifactError(f"bundle artifact selected twice: {relative!r}")
        seen.add(relative)
        target = _regular_file(bundle_root, relative)
        size = target.lstat().st_size
        if size > limits.max_artifact_bytes:
            raise ArtifactError(
                f"artifact {relative!r} of {size} bytes exceeds per-artifact limit {limits.max_artifact_bytes}"
            )
        total += size
        if total > limits.max_total_bytes:
            raise ArtifactError(
                f"artifact {relative!r} brings retained bytes to {total}, which exceeds bundle limit {limits.max_total_bytes}"
            )
        data = target.read_bytes()
        if len(data) != size:
            raise ArtifactError(f"artifact {relative!r} changed size while being read")
        digest = content_digest(data)
        expected = expected_digests.get(relative)
        if expected is not None and expected != digest:
            raise ArtifactError(f"artifact {relative!r} digest mismatch: expected {expected}, retained {digest}")
        retained.append(RetainedArtifact(item.role, relative, digest, data))
    return tuple(retained)
