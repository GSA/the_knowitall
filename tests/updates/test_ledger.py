from dataclasses import replace

import pytest

from knowitall_publication import PublicationStore


def ledger(root):
    from knowitall_updates import UpdateLedger
    return UpdateLedger(root / "updates", PublicationStore(root / "store"))


def submit(instance, snapshot, key="update-a", **kwargs):
    return instance.submit(key, snapshot, expected_current=None, engine_identity="graphifyy:0.9.96", runtime_identity="runtime-a", config_identity=kwargs.get("config", "config-a"))


def test_acknowledged_request_survives_reopen_and_snapshot_source_removal(generation_factory, tmp_path):
    _, snapshot = generation_factory()
    instance = ledger(tmp_path)
    status = submit(instance, snapshot)
    reopened = ledger(tmp_path)
    assert reopened.inspect("update-a") == status
    assert reopened.load_snapshot("update-a").included == snapshot.included
    assert status.phase == "requested"
    assert status.receipt is None


def test_exact_retry_and_identity_conflict(generation_factory, tmp_path):
    from knowitall_updates import UpdateConflict
    _, snapshot = generation_factory()
    instance = ledger(tmp_path)
    first = submit(instance, snapshot)
    assert submit(instance, snapshot) == first
    with pytest.raises(UpdateConflict):
        submit(instance, snapshot, config="config-b")
    with pytest.raises(UpdateConflict):
        submit(instance, replace(snapshot, commit="different"))


def test_saved_source_corruption_fails_closed(generation_factory, tmp_path):
    from knowitall_updates import UpdateValidationError
    _, snapshot = generation_factory()
    instance = ledger(tmp_path)
    submit(instance, snapshot)
    source = next((tmp_path / "updates").glob("requests/*/source/src/*.py"))
    source.write_bytes(b"altered source")
    with pytest.raises(UpdateValidationError):
        ledger(tmp_path).load_snapshot("update-a")


def test_path_like_key_never_escapes_private_state(generation_factory, tmp_path):
    _, snapshot = generation_factory()
    instance = ledger(tmp_path)
    submit(instance, snapshot, "../../escape")
    assert instance.inspect("../../escape").request_id == "../../escape"
    assert all(path.resolve().is_relative_to(instance.root.resolve()) for path in instance.root.rglob("*"))


def test_invalid_admitted_bytes_are_not_acknowledged(generation_factory, tmp_path):
    from knowitall_updates import UpdateValidationError
    _, snapshot = generation_factory()
    entry = replace(snapshot.included[0], data=b"different")
    invalid = replace(snapshot, included=(entry, *snapshot.included[1:]))
    with pytest.raises(UpdateValidationError):
        submit(ledger(tmp_path), invalid)
