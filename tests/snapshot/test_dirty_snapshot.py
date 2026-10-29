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


def test_admitted_tracked_mode_change_is_preserved(make_repo, tmp_path):
    repo = make_repo()
    changed = repo / "src" / "orders.py"
    changed.chmod(0o755)
    policy = SnapshotPolicy(dirty="admit", tracked_changes="include")

    snapshot = create_snapshot(repo, "project", "repo", tmp_path / "out", policy)

    entry = next(item for item in snapshot.included if item.path == "src/orders.py")
    assert entry.mode == "100755"
    assert (tmp_path / "out" / snapshot.snapshot_id / "source" / "src" / "orders.py").stat().st_mode & 0o111


def test_dirty_snapshot_aborts_when_admitted_bytes_change_during_capture(make_repo, tmp_path, monkeypatch):
    repo = make_repo()
    changed = repo / "src" / "orders.py"
    changed.write_text("first dirty value\n", encoding="utf-8")
    import knowitall_snapshot.materialize as materialize

    real_inventory = materialize._dirty_inventory

    def racing_inventory(*args):
        inventory = real_inventory(*args)
        changed.write_text("second dirty value\n", encoding="utf-8")
        return inventory

    monkeypatch.setattr(materialize, "_dirty_inventory", racing_inventory)

    with pytest.raises(ValueError, match="repository changed during snapshot"):
        create_snapshot(repo, "project", "repo", tmp_path / "out", SnapshotPolicy(dirty="admit", tracked_changes="include"))
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_admitted_deleted_file_is_absent_from_snapshot(make_repo, tmp_path):
    repo = make_repo()
    (repo / "src" / "store.py").unlink()

    snapshot = create_snapshot(
        repo, "project", "repo", tmp_path / "out",
        SnapshotPolicy(dirty="admit", tracked_changes="include"),
    )

    assert "src/store.py" not in {entry.path for entry in snapshot.included}
    assert not (tmp_path / "out" / snapshot.snapshot_id / "source" / "src" / "store.py").exists()


def test_admitted_rename_removes_old_path_and_captures_new_path(make_repo, tmp_path):
    repo = make_repo()
    (repo / "src" / "store.py").rename(repo / "src" / "persistence.py")

    snapshot = create_snapshot(
        repo, "project", "repo", tmp_path / "out",
        SnapshotPolicy(dirty="admit", tracked_changes="include", untracked_files="include"),
    )

    paths = {entry.path for entry in snapshot.included}
    assert "src/store.py" not in paths
    assert "src/persistence.py" in paths


def test_excluded_untracked_file_contents_are_not_read(make_repo, tmp_path, monkeypatch):
    repo = make_repo()
    excluded = repo / "unreadable.bin"
    excluded.write_bytes(b"excluded")
    original_read_bytes = type(excluded).read_bytes

    def guarded_read_bytes(path):
        if path == excluded:
            raise PermissionError("excluded file must not be read")
        return original_read_bytes(path)

    monkeypatch.setattr(type(excluded), "read_bytes", guarded_read_bytes)

    snapshot = create_snapshot(repo, "project", "repo", tmp_path / "out", SnapshotPolicy(dirty="admit"))

    assert {"path": "unreadable.bin", "reason": "dirty_untracked_excluded"} in snapshot.excluded


def test_dirty_policy_records_excluded_working_changes(make_repo, tmp_path):
    repo = make_repo()
    (repo / "src" / "orders.py").write_text("changed = True\n", encoding="utf-8")
    (repo / "notes.txt").write_text("not included\n", encoding="utf-8")

    snapshot = create_snapshot(repo, "project", "repo", tmp_path / "out", SnapshotPolicy(dirty="admit"))

    reasons = {(entry["path"], entry["reason"]) for entry in snapshot.excluded}
    assert ("src/orders.py", "dirty_tracked_excluded") in reasons
    assert ("notes.txt", "dirty_untracked_excluded") in reasons
