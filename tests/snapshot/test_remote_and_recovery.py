import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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


def test_remote_refresh_never_executes_checkout_filters(make_repo, tmp_path):
    upstream = make_repo()
    remote = tmp_path / "upstream.git"
    git(upstream, "clone", "--bare", "-q", str(upstream), str(remote))
    checkout = acquire_remote(str(remote), tmp_path / "checkout")
    marker = tmp_path / "smudge-ran"
    filter_command = f"sh -c 'touch {marker}; cat'"
    git(checkout.path, "config", "filter.hostile.smudge", filter_command)
    git(checkout.path, "config", "filter.hostile.required", "true")
    (upstream / ".gitattributes").write_text("*.py filter=hostile\n", encoding="utf-8")
    git(upstream, "add", ".")
    git(upstream, "commit", "-qm", "add filter attributes")
    git(upstream, "push", "-q", str(remote), "HEAD")

    acquire_remote(str(remote), checkout.path)

    assert not marker.exists()
    assert (checkout.path / "src" / "orders.py").is_file()
    configured_filters = subprocess.run(
        ["git", "config", "--get-regexp", "^filter\\."],
        cwd=checkout.path,
        capture_output=True,
        check=False,
    )
    assert configured_filters.returncode == 1


def test_acquired_symlink_repository_can_be_snapshotted_with_default_policy(make_repo, tmp_path):
    upstream = make_repo()
    os.symlink("src/orders.py", upstream / "orders-link.py")
    git(upstream, "add", "orders-link.py")
    git(upstream, "commit", "-qm", "add symlink")
    remote = tmp_path / "upstream.git"
    git(upstream, "clone", "--bare", "-q", str(upstream), str(remote))

    checkout = acquire_remote(str(remote), tmp_path / "checkout")
    snapshot = create_snapshot(checkout.path, "project", "repository", tmp_path / "snapshots", SnapshotPolicy())

    assert any(item["path"] == "orders-link.py" and item["reason"] == "symlink_excluded" for item in snapshot.excluded)


def test_acquired_submodule_repository_can_be_snapshotted_with_default_policy(make_repo, tmp_path):
    child = make_repo("typescript_client")
    upstream = make_repo()
    git(upstream, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(child), "vendor/client")
    git(upstream, "commit", "-qm", "add submodule")
    remote = tmp_path / "upstream.git"
    git(upstream, "clone", "--bare", "-q", str(upstream), str(remote))

    checkout = acquire_remote(str(remote), tmp_path / "checkout")
    snapshot = create_snapshot(checkout.path, "project", "repository", tmp_path / "snapshots", SnapshotPolicy())

    assert any(item["path"] == "vendor/client" and item["reason"] == "submodule_excluded" for item in snapshot.excluded)


@pytest.mark.skipif(os.name != "posix", reason="byte-valued symlink targets require POSIX")
def test_acquired_non_utf8_symlink_can_be_snapshotted_with_default_policy(make_repo, tmp_path):
    upstream = make_repo()
    os.symlink(b"non-utf8-\xff", os.fsencode(upstream / "raw-link"))
    git(upstream, "add", "raw-link")
    git(upstream, "commit", "-qm", "add byte-valued symlink")
    remote = tmp_path / "upstream.git"
    git(upstream, "clone", "--bare", "-q", str(upstream), str(remote))

    checkout = acquire_remote(str(remote), tmp_path / "checkout")
    checkout = acquire_remote(str(remote), checkout.path)
    snapshot = create_snapshot(checkout.path, "project", "repository", tmp_path / "snapshots", SnapshotPolicy())

    assert os.readlink(os.fsencode(checkout.path / "raw-link")) == b"non-utf8-\xff"
    assert any(item["path"] == "raw-link" and item["reason"] == "symlink_excluded" for item in snapshot.excluded)


def test_remote_discovery_never_invokes_checkout_credential_helper(make_repo, tmp_path, monkeypatch):
    current = make_repo()
    marker = tmp_path / "credential-helper-ran"
    helper = tmp_path / "helper.sh"
    helper.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    helper.chmod(0o755)
    git(current, "config", "credential.helper", str(helper))

    class AuthRequired(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="test"')
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), AuthRequired)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    git(current, "config", f"url.http://127.0.0.1:{server.server_port}/.insteadOf", "https://credential-test.invalid/")
    monkeypatch.chdir(current)
    try:
        with pytest.raises(Exception):
            acquire_remote("https://credential-test.invalid/repo.git", tmp_path / "checkout")
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    assert not marker.exists()


def test_remote_intake_rejects_credential_bearing_origins(tmp_path):
    with pytest.raises(ValueError, match="credentials"):
        acquire_remote("https://user:secret@example.invalid/repo.git", tmp_path / "checkout")


def test_sha256_remote_acquisition_and_refresh_preserve_object_format(make_repo, tmp_path):
    if subprocess.run(["git", "init", "--object-format=sha256", "--bare", str(tmp_path / "probe")], capture_output=True).returncode:
        pytest.skip("Git does not support SHA-256 repositories")
    upstream = tmp_path / "upstream-sha256"
    upstream.mkdir()
    git(upstream, "init", "--object-format=sha256", "-q")
    git(upstream, "config", "user.name", "Synthetic Test")
    git(upstream, "config", "user.email", "synthetic@example.invalid")
    (upstream / "source.py").write_text("value = 1\n", encoding="utf-8")
    git(upstream, "add", ".")
    git(upstream, "commit", "-qm", "fixture")
    remote = tmp_path / "upstream-sha256.git"
    git(upstream, "clone", "--bare", "-q", str(upstream), str(remote))

    checkout = acquire_remote(str(remote), tmp_path / "checkout")
    acquire_remote(str(remote), checkout.path)

    assert git(checkout.path, "rev-parse", "--show-object-format") == "sha256"
    assert create_snapshot(checkout.path, "project", "repository", tmp_path / "snapshots", SnapshotPolicy()).commit.startswith("sha256:")


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
