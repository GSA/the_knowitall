import pytest

from knowitall_publication import PublicationStore
from knowitall_publication import durable
from knowitall_updates import UpdateLedger


@pytest.mark.parametrize("component", ["store", "ledger"])
def test_reopened_initialization_requires_parent_durability(
    tmp_path, monkeypatch, component
):
    store = PublicationStore(tmp_path / "store") if component == "ledger" else None
    root = tmp_path / "interrupted"
    original_sync = durable.fsync_directory

    def sync(path):
        if path == root.parent:
            raise OSError("initialization parent synchronization failed")
        original_sync(path)

    def initialize():
        if component == "store":
            return PublicationStore(root)
        return UpdateLedger(root, store)

    monkeypatch.setattr(durable, "fsync_directory", sync)
    with pytest.raises(OSError, match="initialization parent synchronization failed"):
        initialize()
    assert root.is_dir()
    # The mkdir is visible after failure, but reopening must not acknowledge
    # usable storage until its parent entry has been synchronized.
    with pytest.raises(OSError, match="initialization parent synchronization failed"):
        initialize()

    monkeypatch.setattr(durable, "fsync_directory", original_sync)
    reopened = initialize()
    assert reopened.root == root
    assert (root / ("requests" if component == "ledger" else "receipts")).is_dir()
