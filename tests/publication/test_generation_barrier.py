import pytest

from knowitall_publication import PublicationStore


@pytest.mark.parametrize("has_predecessor", [False, True])
def test_existing_generation_rename_is_persisted_before_selection(generation_factory, tmp_path, monkeypatch, has_predecessor):
    import knowitall_publication.store as module
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path)
    predecessor = None
    if has_predecessor:
        previous, _ = generation_factory(fixture="typescript_client")
        predecessor = store.publish(store.stage(previous)).generation
    staged = store.stage(generation)
    receipts_before = {path: path.read_bytes() for path in (tmp_path / "receipts").iterdir()}
    original = module._fsync_directory
    def fail(path):
        if path == tmp_path / 'generations':
            raise OSError('generation rename not persisted')
        original(path)
    monkeypatch.setattr(module, '_fsync_directory', fail)
    with pytest.raises(OSError, match="generation rename not persisted"):
        store.publish(staged, expected_current=predecessor)
    assert store._generation_path(generation.generation_id).exists()
    store = PublicationStore(tmp_path)
    with pytest.raises(OSError, match="generation rename not persisted"):
        store.publish(staged, expected_current=predecessor)
    assert {path: path.read_bytes() for path in (tmp_path / "receipts").iterdir()} == receipts_before
    if predecessor is None:
        with pytest.raises(KeyError):
            store.resolve_current('project-a', 'repo-a')
    else:
        assert store.resolve_current('project-a', 'repo-a') == predecessor
    monkeypatch.setattr(module, '_fsync_directory', original)
    receipt = store.publish(staged, expected_current=predecessor)
    assert receipt.generation.generation_id == generation.generation_id
    assert store.resolve_current('project-a', 'repo-a') == receipt.generation
    assert store.open_generation(receipt.generation) == generation
    assert store.publish(staged, expected_current=predecessor) == receipt
