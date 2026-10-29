import os

import pytest

from knowitall_publication import PublicationInterrupted, PublicationStore


@pytest.mark.parametrize("successor", [False, True])
@pytest.mark.parametrize("sync_fails", [False, True])
def test_existing_receipt_retry_persists_rename_before_acknowledgment(
    generation_factory, tmp_path, monkeypatch, successor, sync_fails
):
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path)
    staged = store.stage(generation)
    receipts = tmp_path / "receipts"
    receipts_inode = receipts.stat().st_ino
    original_sync = os.fsync
    fail_sync = True
    receipt_syncs = []

    def sync(descriptor):
        if os.fstat(descriptor).st_ino == receipts_inode:
            if fail_sync:
                raise OSError("receipt directory synchronization failed")
            original_sync(descriptor)
            receipt_syncs.append(True)
        else:
            original_sync(descriptor)

    monkeypatch.setattr(os, "fsync", sync)
    with pytest.raises(OSError, match="receipt directory synchronization failed"):
        store.publish(staged, expected_current=None)
    receipt_path = next(receipts.iterdir())
    receipt_bytes = receipt_path.read_bytes()
    selected = store.resolve_current("project-a", "repo-a")
    assert selected.generation_id == generation.generation_id

    if successor:
        other, _ = generation_factory(fixture="typescript_client")
        other_staged = store.stage(other)
        store = PublicationStore(tmp_path)
        # A visible receipt is not necessarily durable. B must preserve A's
        # selection if the predecessor receipt barrier still fails.
        with pytest.raises(OSError, match="receipt directory synchronization failed"):
            store.publish(
                other_staged, expected_current=selected,
                failpoint="after_current_replace",
            )
        assert store.resolve_current("project-a", "repo-a") == selected
        assert receipt_path.read_bytes() == receipt_bytes
        assert receipt_syncs == []

        fail_sync = False
        with pytest.raises(PublicationInterrupted):
            store.publish(
                other_staged, expected_current=selected,
                failpoint="after_current_replace",
            )
        selected = store.resolve_current("project-a", "repo-a")
        assert selected.generation_id == other.generation_id
        assert receipt_syncs == [True]
        assert list(receipts.iterdir()) == [receipt_path]
        receipt_syncs.clear()

    # Reopen after interruption: the receipt is visible but its rename is not
    # yet durable. A failed barrier must not acknowledge even a historical retry.
    store = PublicationStore(tmp_path)
    fail_sync = sync_fails
    if sync_fails:
        with pytest.raises(OSError, match="receipt directory synchronization failed"):
            store.publish(staged, expected_current=None)
        assert receipt_syncs == []
        assert store.resolve_current("project-a", "repo-a") == selected
        fail_sync = False

    receipt = store.publish(staged, expected_current=None)
    assert receipt_syncs == [True]
    assert receipt.generation.generation_id == generation.generation_id
    assert receipt_path.read_bytes() == receipt_bytes
    assert store.resolve_current("project-a", "repo-a") == selected
    assert store.open_generation(receipt.generation) == generation
