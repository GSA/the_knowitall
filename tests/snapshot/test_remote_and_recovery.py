import os
import shutil
from pathlib import Path

import pytest

from conftest import git
from knowitall_snapshot import SnapshotPolicy, acquire_remote, create_snapshot


def test_remote_clone_and_fetch_capture_origin_without_changing_repository_identity(make_repo, tmp_path):
    upstream = make_repo()
    remote = tmp_path / "upstream.git"
    git(upstream, "clone", "--bare", "-q", str(upstream), str(remote))

    checkout = acquire_remote(str(remote), tmp_path / "checkout")
    first = create_snapshot(
        checkout.path,
        "project",
        "repository",
        tmp_path / "snapshots",
        SnapshotPolicy(),
        origin=checkout.origin,
    )

    (upstream / "src" / "orders.py").write_text("changed = True\n", encoding="utf-8")
    git(upstream, "add", ".")
    git(upstream, "commit", "-qm", "change")
    git(upstream, "push", "-q", str(remote), "HEAD")

    refreshed = acquire_remote(str(remote), tmp_path / "checkout")
    second = create_snapshot(
        refreshed.path,
        "project",
        "repository",
        tmp_path / "snapshots",
        SnapshotPolicy(),
        origin=refreshed.origin,
    )

    assert first.repository_id == second.repository_id == "repository"
    assert first.origin == second.origin == str(remote.resolve())
    assert first.snapshot_id != second.snapshot_id
    assert first.commit != second.commit


def test_remote_intake_rejects_credential_bearing_origins(tmp_path):
    with pytest.raises(ValueError, match="credentials"):
        acquire_remote("https://user:secret@example.invalid/repo.git", tmp_path / "checkout")


def test_materialization_preserves_executable_permission(make_repo, tmp_path):
    repo = make_repo()
    script = repo / "tool.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    git(repo, "add", "tool.sh")
    git(repo, "commit", "-qm", "executable")

    snapshot = create_snapshot(repo, "project", "repository", tmp_path / "snapshots", SnapshotPolicy())
    materialized = tmp_path / "snapshots" / snapshot.snapshot_id / "source" / "tool.sh"

    assert next(entry for entry in snapshot.included if entry.path == "tool.sh").mode == "100755"
    assert materialized.stat().st_mode & 0o111


def test_mode_only_change_produces_a_distinct_snapshot_identity(make_repo, tmp_path):
    repo = make_repo()
    destination = tmp_path / "snapshots"
    first = create_snapshot(repo, "project", "repository", destination, SnapshotPolicy())

    orders = repo / "src" / "orders.py"
    orders.chmod(0o755)
    git(repo, "add", "src/orders.py")
    git(repo, "commit", "-qm", "make executable")
    second = create_snapshot(repo, "project", "repository", destination, SnapshotPolicy())

    assert first.content_manifest_digest != second.content_manifest_digest
    assert first.snapshot_id != second.snapshot_id


def test_interrupted_materialization_recovers_without_publishing_partial_snapshot(make_repo, tmp_path, monkeypatch):
    repo = make_repo()
    destination = tmp_path / "snapshots"
    import knowitall_snapshot.materialize as materialize

    real_replace = materialize.os.replace
    monkeypatch.setattr(materialize.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("interrupted")))
    with pytest.raises(OSError, match="interrupted"):
        create_snapshot(repo, "project", "repository", destination, SnapshotPolicy())

    assert not any(path.name.startswith("snap-") for path in destination.iterdir())
    assert not any(path.name.startswith(".snapshot-") for path in destination.iterdir())

    monkeypatch.setattr(materialize.os, "replace", real_replace)
    recovered = create_snapshot(repo, "project", "repository", destination, SnapshotPolicy())
    assert (destination / recovered.snapshot_id / "manifest.json").is_file()


def test_snapshot_survives_removed_remote_and_changed_checkout(make_repo, tmp_path):
    upstream = make_repo()
    remote = tmp_path / "upstream.git"
    git(upstream, "clone", "--bare", "-q", str(upstream), str(remote))
    acquired = acquire_remote(str(remote), tmp_path / "checkout")
    snapshot = create_snapshot(
        acquired.path,
        "project",
        "repository",
        tmp_path / "snapshots",
        SnapshotPolicy(),
        origin=acquired.origin,
    )
    retained = tmp_path / "snapshots" / snapshot.snapshot_id / "source" / "src" / "orders.py"
    retained_bytes = retained.read_bytes()

    shutil.rmtree(remote)
    (acquired.path / "src" / "orders.py").write_text("working tree changed\n", encoding="utf-8")

    assert retained.read_bytes() == retained_bytes
    assert snapshot.inventory_complete is True
