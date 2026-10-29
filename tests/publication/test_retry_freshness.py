import json
from dataclasses import asdict

import pytest

from knowitall_publication import PublicationConflict, PublicationStore, PublicationValidationError


def test_historical_retry_does_not_roll_current_backward(generation_factory, tmp_path):
    first, _ = generation_factory()
    second, _ = generation_factory(fixture="typescript_client")
    store = PublicationStore(tmp_path / "store")
    receipt = store.publish(store.stage(first))
    store.publish(store.stage(second))
    assert PublicationStore(store.root).publish(store.resume(first.generation_id)) == receipt
    assert store.resolve_current("project-a", "repo-a").generation_id == second.generation_id


def test_explicit_predecessor_conflicts_when_current_advanced(generation_factory, tmp_path):
    first, _ = generation_factory()
    second, _ = generation_factory(fixture="typescript_client")
    from knowitall_graphify import normalize_generation
    _, snapshot = generation_factory()
    raw = json.loads(first.raw_artifact)
    raw["source_snapshot_id"] = snapshot.snapshot_id
    raw["nodes"][0]["name"] = "third-target"
    third = normalize_generation(snapshot, json.dumps(raw).encode())
    store = PublicationStore(tmp_path / "store")
    predecessor = store.publish(store.stage(first)).generation
    store.publish(store.stage(second), expected_current=predecessor)
    with pytest.raises(PublicationConflict):
        store.publish(store.stage(third), expected_current=predecessor)


def test_read_and_recovery_reject_corrupt_artifacts(generation_factory, tmp_path):
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path / "store")
    receipt = store.publish(store.stage(generation))
    next((store.root / "generations").glob("*/artifact.bin")).write_bytes(b"corrupt")
    with pytest.raises(PublicationValidationError):
        store.open_generation(receipt.generation)
    with pytest.raises(PublicationValidationError):
        store.resolve_current("project-a", "repo-a")
    # The separately retained valid stage remains recoverable.
    next((store.root / "stages").glob("*/artifact.bin")).write_bytes(b"corrupt")
    assert generation.generation_id not in store.recover()


def test_current_pointer_cannot_borrow_other_repository(generation_factory, tmp_path):
    first, _ = generation_factory(repository="repo-a")
    second, _ = generation_factory(repository="repo-b")
    store = PublicationStore(tmp_path / "store")
    store.publish(store.stage(first))
    other = store.publish(store.stage(second))
    pointer = store._current_path("project-a", "repo-a")
    pointer.write_text(json.dumps(asdict(other.generation)))
    with pytest.raises(PublicationValidationError):
        store.resolve_current("project-a", "repo-a")
