import pytest

from knowitall_publication import PublicationInterrupted, PublicationStore, PublicationValidationError


@pytest.mark.parametrize('successor', [False, True])
@pytest.mark.parametrize('sync_fails', [False, True])
def test_recovered_receipt_requires_current_durability_first(generation_factory, tmp_path, monkeypatch, successor, sync_fails):
    import knowitall_publication.store as module
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path)
    staged = store.stage(generation)
    with pytest.raises(PublicationInterrupted):
        store.publish(staged, expected_current=None, failpoint='after_current_replace')
    events = []
    original_sync, original_write = module._fsync_directory, module.atomic_write
    def sync(path):
        if path == tmp_path / 'current':
            if sync_fails:
                raise OSError('current durability failed')
            original_sync(path)
            events.append('current_sync')
        else:
            original_sync(path)
    def write(path, data):
        if path.parent == tmp_path / 'receipts':
            assert 'current_sync' in events, 'recovered receipt preceded current durability'
        original_write(path, data)
        if path.parent == tmp_path / 'receipts':
            events.clear()
    monkeypatch.setattr(module, '_fsync_directory', sync)
    monkeypatch.setattr(module, 'atomic_write', write)
    target, predecessor = staged, None
    if successor:
        other, _ = generation_factory(fixture='typescript_client')
        target = store.stage(other)
        predecessor = store.resolve_current('project-a', 'repo-a')
    if sync_fails:
        with pytest.raises(OSError, match='current durability failed'):
            store.publish(target, expected_current=predecessor)
        assert not list((tmp_path / 'receipts').iterdir())
        assert store.resolve_current('project-a', 'repo-a').generation_id == generation.generation_id
    else:
        receipt = store.publish(target, expected_current=predecessor)
        assert store.publish(staged).generation.generation_id == generation.generation_id
        assert store.resolve_current('project-a', 'repo-a') == receipt.generation


@pytest.mark.parametrize('name', ['artifact.bin', 'metadata.json', 'metadata.sha256'])
def test_missing_selected_evidence_is_not_empty_current(generation_factory, request_factory, tmp_path, name):
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path)
    store.publish(store.stage(generation))
    pointer = next((tmp_path / 'current').iterdir())
    original = pointer.read_bytes()
    next((tmp_path / 'generations').glob('*/' + name)).unlink()
    from knowitall_query import QueryService
    assert QueryService(store).execute(request_factory())['status'] == 'unavailable'
    with pytest.raises(PublicationValidationError):
        store.resolve_current('project-a', 'repo-a')
    other, _ = generation_factory(fixture='typescript_client')
    with pytest.raises(PublicationValidationError):
        store.publish(store.stage(other), expected_current=None)
    assert pointer.read_bytes() == original
