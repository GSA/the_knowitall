import os
from pathlib import Path

import pytest

from knowitall_snapshot import SnapshotPolicy, create_snapshot
from knowitall_snapshot.git import GitError
from knowitall_snapshot.inventory import safe_path
from conftest import git


@pytest.mark.parametrize("path", ["/absolute.py", "src/../escape.py", "src//empty.py"])
def test_unsafe_inventory_paths_are_rejected(path):
    with pytest.raises(ValueError, match="unsafe repository path"):
        safe_path(path)


def test_symlink_is_not_dereferenced(make_repo, tmp_path):
    repo = make_repo()
    secret = tmp_path / "secret.txt"
    secret.write_text("do not copy", encoding="utf-8")
    os.symlink(secret, repo / "escape")
    git(repo, "add", "escape")
    git(repo, "commit", "-qm", "symlink")

    snapshot = create_snapshot(repo, "project", "repo", tmp_path / "out", SnapshotPolicy())

    assert "escape" not in {entry.path for entry in snapshot.included}
    assert {entry["reason"] for entry in snapshot.excluded if entry["path"] == "escape"} == {"symlink_excluded"}
    assert not (tmp_path / "out" / snapshot.snapshot_id / "source" / "escape").exists()


def test_nested_repository_is_explicitly_excluded(make_repo, tmp_path):
    repo = make_repo()
    nested = repo / "vendor" / "nested"
    nested.mkdir(parents=True)
    git(nested, "init", "-q")
    (nested / "private.py").write_text("secret = True\n", encoding="utf-8")

    snapshot = create_snapshot(repo, "project", "repo", tmp_path / "out", SnapshotPolicy(dirty="admit", untracked_files="include"))

    assert any(item["path"] == "vendor/nested" and item["reason"] == "nested_repository_excluded" for item in snapshot.excluded)
    assert not any(entry.path.endswith("private.py") for entry in snapshot.included)


def test_submodule_gitlink_is_excluded_without_checkout_read(make_repo, tmp_path):
    child = make_repo("typescript_client")
    parent = make_repo()
    git(parent, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(child), "vendor/client")
    git(parent, "commit", "-qm", "submodule")

    snapshot = create_snapshot(parent, "project", "repo", tmp_path / "out", SnapshotPolicy())

    assert any(item["path"] == "vendor/client" and item["reason"] == "submodule_excluded" for item in snapshot.excluded)
    assert not (tmp_path / "out" / snapshot.snapshot_id / "source" / "vendor" / "client").exists()


def test_lfs_pointer_is_preserved_as_pointer(make_repo, tmp_path):
    repo = make_repo()
    pointer = "version https://git-lfs.github.com/spec/v1\noid sha256:" + "a" * 64 + "\nsize 123\n"
    (repo / "asset.bin").write_text(pointer, encoding="utf-8")
    git(repo, "add", "asset.bin")
    git(repo, "commit", "-qm", "lfs pointer")

    snapshot = create_snapshot(repo, "project", "repo", tmp_path / "out", SnapshotPolicy())

    assert (tmp_path / "out" / snapshot.snapshot_id / "source" / "asset.bin").read_text() == pointer


def test_inventory_failure_does_not_return_a_deletion_authority(make_repo, tmp_path, monkeypatch):
    repo = make_repo()
    import knowitall_snapshot.materialize as materialize

    monkeypatch.setattr(materialize, "clean_inventory", lambda *_args: (_ for _ in ()).throw(GitError("listing failed")))

    snapshot = create_snapshot(repo, "project", "repo", tmp_path / "out", SnapshotPolicy(inventory_errors="record"))

    assert snapshot.inventory_complete is False
    assert snapshot.included == ()
    assert snapshot.failed == ({"path": ".", "reason": "inventory_listing_failed"},)
