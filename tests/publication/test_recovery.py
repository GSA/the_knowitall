import pytest

from knowitall_publication import PublicationInterrupted, PublicationStore


def test_failure_before_validation_leaves_previous_current(generation_factory, tmp_path):
    first, _ = generation_factory()
    second, _ = generation_factory(fixture="typescript_client")
    store = PublicationStore(tmp_path / "store")
    store.publish(store.stage(first))

    with pytest.raises(PublicationInterrupted):
        store.publish(store.stage(second), failpoint="before_validation")

    assert store.resolve_current("project-a", "repo-a").generation_id == first.generation_id


@pytest.mark.parametrize("failpoint", ["after_validation", "before_current_replace"])
def test_interruption_before_pointer_replace_keeps_last_known_good(generation_factory, tmp_path, failpoint):
    first, _ = generation_factory()
    second, _ = generation_factory(fixture="typescript_client")
    store = PublicationStore(tmp_path / "store")
    store.publish(store.stage(first))

    with pytest.raises(PublicationInterrupted):
        store.publish(store.stage(second), failpoint=failpoint)

    assert store.resolve_current("project-a", "repo-a").generation_id == first.generation_id
    recovered = PublicationStore(tmp_path / "store").recover()
    assert second.generation_id in recovered
    assert store.resolve_current("project-a", "repo-a").generation_id == first.generation_id


def test_interruption_after_pointer_replace_is_visible_and_retry_deduplicates(generation_factory, tmp_path):
    first, _ = generation_factory()
    second, _ = generation_factory(fixture="typescript_client")
    store = PublicationStore(tmp_path / "store")
    store.publish(store.stage(first))
    staged = store.stage(second)

    with pytest.raises(PublicationInterrupted):
        store.publish(staged, failpoint="after_current_replace")

    assert store.resolve_current("project-a", "repo-a").generation_id == second.generation_id
    recovered = PublicationStore(tmp_path / "store").recover()
    assert second.generation_id in recovered
    assert store.publish(staged).generation.generation_id == second.generation_id
