import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .git import run_git


@dataclass(frozen=True)
class InventoryEntry:
    path: str
    content_digest: str
    data: bytes


def safe_path(value: str) -> PurePosixPath:
    raw_parts = value.split("/")
    path = PurePosixPath(value)
    if path.is_absolute() or not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(f"unsafe repository path: {value!r}")
    return path


def clean_inventory(repo: Path) -> tuple[tuple[InventoryEntry, ...], tuple[dict[str, str], ...]]:
    raw = run_git(repo, "ls-files", "--stage", "-z", text=False)
    included = []
    excluded = []
    for record in filter(None, raw.split(b"\0")):
        metadata, raw_path = record.split(b"\t", 1)
        mode, _object_id, _stage = metadata.split(b" ")
        path = raw_path.decode("utf-8", "strict")
        safe_path(path)
        if mode == b"160000":
            excluded.append({"path": path, "reason": "submodule_excluded"})
            continue
        if mode == b"120000":
            excluded.append({"path": path, "reason": "symlink_excluded"})
            continue
        if mode not in {b"100644", b"100755"}:
            excluded.append({"path": path, "reason": "unsupported_git_mode"})
            continue
        data = run_git(repo, "show", f"HEAD:{path}", text=False)
        included.append(InventoryEntry(path, "sha256:" + hashlib.sha256(data).hexdigest(), data))
    return tuple(sorted(included, key=lambda item: item.path.encode())), tuple(sorted(excluded, key=lambda item: item["path"].encode()))
