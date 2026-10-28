import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .git import GitError, commit_identity, status_entries
from .inventory import InventoryEntry, clean_inventory, safe_path


@dataclass(frozen=True)
class SnapshotPolicy:
    dirty: str = "reject"
    tracked_changes: str = "exclude"
    untracked_files: str = "exclude"
    submodules: str = "exclude"
    lfs: str = "pointers"
    inventory_errors: str = "raise"


@dataclass(frozen=True)
class SnapshotManifest:
    project_id: str
    repository_id: str
    snapshot_id: str
    commit: str
    content_manifest_digest: str
    cleanliness: str
    dirty_content_digest: str | None
    included: tuple[InventoryEntry, ...]
    excluded: tuple[dict[str, str], ...]
    failed: tuple[dict[str, str], ...] = ()
    inventory_complete: bool = True

    def canonical(self) -> bytes:
        value = asdict(self)
        for entry in value["included"]:
            entry.pop("data")
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _identity(*parts: str) -> str:
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _status(repo: Path) -> tuple[set[str], set[str]]:
    tracked: set[str] = set()
    untracked: set[str] = set()
    records = iter(status_entries(repo).split(b"\0"))
    for record in records:
        if not record:
            continue
        code = record[:2]
        path = record[3:].decode("utf-8", "strict")
        if b"R" in code or b"C" in code:
            original = next(records).decode("utf-8", "strict")
            safe_path(original)
            tracked.add(original)
        if code == b"??" and path.endswith("/"):
            path = path[:-1]
        safe_path(path)
        (untracked if code == b"??" else tracked).add(path)
    return tracked, untracked


def _dirty_inventory(repo: Path, included: tuple[InventoryEntry, ...], excluded: tuple[dict[str, str], ...], policy: SnapshotPolicy, tracked: set[str], untracked: set[str]):
    entries = {entry.path: entry for entry in included}
    exclusions = list(excluded)
    for path in sorted(tracked, key=str.encode):
        if policy.tracked_changes == "include":
            target = repo / path
            if target.is_file() and not target.is_symlink():
                data = target.read_bytes()
                entries[path] = InventoryEntry(path, "sha256:" + hashlib.sha256(data).hexdigest(), data)
            else:
                entries.pop(path, None)
        else:
            exclusions.append({"path": path, "reason": "dirty_tracked_excluded"})
    nested_roots: set[str] = set()
    for path in sorted(untracked, key=str.encode):
        parts = path.split("/")
        nested = next(("/".join(parts[:index]) for index in range(1, len(parts) + 1) if (repo / "/".join(parts[:index]) / ".git").exists()), None)
        if nested:
            if nested not in nested_roots:
                exclusions.append({"path": nested, "reason": "nested_repository_excluded"})
                nested_roots.add(nested)
            continue
        target = repo / path
        if policy.untracked_files == "include" and target.is_file() and not target.is_symlink():
            data = target.read_bytes()
            entries[path] = InventoryEntry(path, "sha256:" + hashlib.sha256(data).hexdigest(), data)
        else:
            exclusions.append({"path": path, "reason": "dirty_untracked_excluded"})
    return tuple(sorted(entries.values(), key=lambda item: item.path.encode())), tuple(sorted(exclusions, key=lambda item: item["path"].encode()))


def create_snapshot(repo: Path, project_id: str, repository_id: str, destination: Path, policy: SnapshotPolicy) -> SnapshotManifest:
    if not project_id or not repository_id:
        raise ValueError("project and repository identities must be nonempty")
    tracked, untracked = _status(repo)
    dirty = bool(tracked or untracked)
    if dirty and policy.dirty != "admit":
        raise ValueError("dirty Git input rejected by policy")
    commit = commit_identity(repo)
    try:
        included, excluded = clean_inventory(repo)
        failed: tuple[dict[str, str], ...] = ()
        inventory_complete = True
    except GitError:
        if policy.inventory_errors != "record":
            raise
        included, excluded = (), ()
        failed = ({"path": ".", "reason": "inventory_listing_failed"},)
        inventory_complete = False
    if dirty and inventory_complete:
        included, excluded = _dirty_inventory(repo, included, excluded, policy, tracked, untracked)
    content_bytes = b"".join(entry.path.encode() + b"\0" + entry.content_digest.encode() + b"\0" for entry in included)
    content_digest = "sha256:" + hashlib.sha256(content_bytes).hexdigest()
    dirty_digest = "sha256:" + hashlib.sha256(status_entries(repo) + content_bytes).hexdigest() if dirty else None
    snapshot_id = "snap-" + _identity(project_id, repository_id, commit, content_digest, dirty_digest or "", policy.submodules, policy.lfs)
    manifest = SnapshotManifest(project_id, repository_id, snapshot_id, commit, content_digest, "dirty" if dirty else "clean", dirty_digest, included, excluded, failed, inventory_complete)
    manifest_bytes = manifest.canonical()
    target = destination / snapshot_id
    if target.exists():
        if (target / "manifest.json").read_bytes() != manifest_bytes:
            raise ValueError("existing snapshot identity has different manifest bytes")
        return manifest
    destination.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=destination))
    try:
        source = temporary / "source"
        for entry in included:
            output = source / entry.path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(entry.data)
        (temporary / "manifest.json").write_bytes(manifest_bytes)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest
