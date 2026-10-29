import hashlib
import json
import shutil
from pathlib import Path

import pytest

from knowitall_snapshot import SnapshotPolicy, create_snapshot
from conftest import git


def test_clean_snapshot_has_exact_stable_identities_and_inventory(make_repo, tmp_path):
    repo = make_repo("python_service")
    first = create_snapshot(repo, "Project-A", "Repo-A", tmp_path / "snapshots", SnapshotPolicy())
    moved = tmp_path / "moved-checkout"
    shutil.move(repo, moved)
    second = create_snapshot(moved, "Project-A", "Repo-A", tmp_path / "snapshots", SnapshotPolicy())

    assert first == second
    assert first.project_id == "Project-A"
    assert first.repository_id == "Repo-A"
    assert first.commit.startswith("sha1:")
    assert first.content_manifest_digest.startswith("sha256:")
    assert [entry.path for entry in first.included] == ["src/orders.py", "src/store.py"]
    root = tmp_path / "snapshots" / first.snapshot_id
    assert (root / "source" / "src" / "orders.py").is_file()
    assert json.loads((root / "manifest.json").read_text())["snapshot_id"] == first.snapshot_id


def test_two_repositories_and_similar_ids_never_fallback(make_repo, tmp_path):
    python_repo = make_repo("python_service")
    ts_repo = make_repo("typescript_client")
    destination = tmp_path / "snapshots"

    python = create_snapshot(python_repo, "Project-é", "Repo-A", destination, SnapshotPolicy())
    typescript = create_snapshot(ts_repo, "Project-é", "repo-a", destination, SnapshotPolicy())

    assert python.snapshot_id != typescript.snapshot_id
    assert python.project_id != typescript.project_id
    assert python.repository_id != typescript.repository_id
    assert {entry.path for entry in typescript.included} == {"src/api.ts", "src/client.ts"}


def test_snapshot_aborts_when_head_changes_after_initial_status(make_repo, tmp_path, monkeypatch):
    repo = make_repo()
    destination = tmp_path / "snapshots"
    import knowitall_snapshot.materialize as materialize

    real_status = materialize.status_entries
    calls = 0

    def racing_status(*args):
        nonlocal calls
        status = real_status(*args)
        calls += 1
        if calls == 1:
            (repo / "src" / "orders.py").write_text("raced = True\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "race")
        return status

    monkeypatch.setattr(materialize, "status_entries", racing_status)

    with pytest.raises(ValueError, match="repository changed during snapshot"):
        create_snapshot(repo, "project", "repo", destination, SnapshotPolicy())
    assert not destination.exists() or not any(destination.iterdir())


def test_snapshot_aborts_when_head_changes_during_inventory(make_repo, tmp_path, monkeypatch):
    repo = make_repo()
    destination = tmp_path / "snapshots"
    import knowitall_snapshot.materialize as materialize

    real_inventory = materialize.clean_inventory

    def racing_inventory(*args):
        inventory = real_inventory(*args)
        (repo / "src" / "orders.py").write_text("raced = True\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "race")
        return inventory

    monkeypatch.setattr(materialize, "clean_inventory", racing_inventory)

    with pytest.raises(ValueError, match="repository changed during snapshot"):
        create_snapshot(repo, "project", "repo", destination, SnapshotPolicy())
    assert not destination.exists() or not any(destination.iterdir())


def test_snapshot_aborts_when_head_changes_during_manifest_construction(make_repo, tmp_path, monkeypatch):
    repo = make_repo()
    destination = tmp_path / "snapshots"
    import knowitall_snapshot.materialize as materialize

    real_canonical = materialize.SnapshotManifest.canonical

    def racing_canonical(manifest):
        (repo / "src" / "orders.py").write_text("raced = True\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "race")
        return real_canonical(manifest)

    monkeypatch.setattr(materialize.SnapshotManifest, "canonical", racing_canonical)

    with pytest.raises(ValueError, match="repository changed during snapshot"):
        create_snapshot(repo, "project", "repo", destination, SnapshotPolicy())
    assert not destination.exists() or not any(destination.iterdir())


def test_existing_snapshot_identity_with_changed_manifest_is_rejected(make_repo, tmp_path):
    repo = make_repo()
    destination = tmp_path / "snapshots"
    manifest = create_snapshot(repo, "project", "repo", destination, SnapshotPolicy())
    manifest_path = destination / manifest.snapshot_id / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="existing snapshot identity"):
        create_snapshot(repo, "project", "repo", destination, SnapshotPolicy())
