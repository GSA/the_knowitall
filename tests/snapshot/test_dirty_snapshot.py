from pathlib import Path

import pytest

from knowitall_snapshot import SnapshotPolicy, create_snapshot


def test_tracked_change_is_rejected_by_default(make_repo, tmp_path):
    repo = make_repo()
    (repo / "src" / "orders.py").write_text("changed = True\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dirty Git input"):
        create_snapshot(repo, "project", "repo", tmp_path / "out", SnapshotPolicy())


def test_untracked_file_is_rejected_by_default(make_repo, tmp_path):
    repo = make_repo()
    (repo / "notes.txt").write_text("not admitted by accident", encoding="utf-8")

    with pytest.raises(ValueError, match="dirty Git input"):
        create_snapshot(repo, "project", "repo", tmp_path / "out", SnapshotPolicy())


def test_explicit_dirty_policy_binds_included_working_bytes(make_repo, tmp_path):
    repo = make_repo()
    changed = repo / "src" / "orders.py"
    changed.write_text("changed = True\n", encoding="utf-8")
    (repo / "notes.txt").write_text("included note\n", encoding="utf-8")
    policy = SnapshotPolicy(dirty="admit", tracked_changes="include", untracked_files="include")

    dirty = create_snapshot(repo, "project", "repo", tmp_path / "out", policy)

    assert dirty.cleanliness == "dirty"
    assert dirty.dirty_content_digest.startswith("sha256:")
    assert dirty.dirty_content_digest != dirty.content_manifest_digest
    assert {entry.path for entry in dirty.included} == {"src/orders.py", "src/store.py", "notes.txt"}
    assert (tmp_path / "out" / dirty.snapshot_id / "source" / "src" / "orders.py").read_text() == "changed = True\n"
    assert dirty.snapshot_id != create_snapshot(repo, "project", "repo", tmp_path / "other", SnapshotPolicy(dirty="admit")).snapshot_id


def test_dirty_policy_records_excluded_working_changes(make_repo, tmp_path):
    repo = make_repo()
    (repo / "src" / "orders.py").write_text("changed = True\n", encoding="utf-8")
    (repo / "notes.txt").write_text("not included\n", encoding="utf-8")

    snapshot = create_snapshot(repo, "project", "repo", tmp_path / "out", SnapshotPolicy(dirty="admit"))

    reasons = {(entry["path"], entry["reason"]) for entry in snapshot.excluded}
    assert ("src/orders.py", "dirty_tracked_excluded") in reasons
    assert ("notes.txt", "dirty_untracked_excluded") in reasons
