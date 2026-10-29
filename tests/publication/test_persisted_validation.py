import json

import pytest

from knowitall_publication import PublicationInterrupted, PublicationStore, PublicationValidationError
from knowitall_query import QueryService


def test_ambiguous_older_publication_retry_after_newer_selection(generation_factory, tmp_path):
    first, _ = generation_factory()
    second, _ = generation_factory(fixture="typescript_client")
    store = PublicationStore(tmp_path / "store")
    with pytest.raises(PublicationInterrupted):
        store.publish(store.stage(first), failpoint="after_current_replace")
    store.publish(store.stage(second))
    receipt = PublicationStore(store.root).publish(store.resume(first.generation_id))
    assert receipt.generation.generation_id == first.generation_id
    assert store.resolve_current("project-a", "repo-a").generation_id == second.generation_id


@pytest.mark.parametrize("mutation", ["name", "malformed", "model"])
def test_invalid_persisted_metadata_is_unavailable(generation_factory, tmp_path, request_factory, mutation):
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path / "store")
    reference = store.publish(store.stage(generation)).generation
    path = next((store.root / "generations").glob("*/metadata.json"))
    value = json.loads(path.read_bytes())
    if mutation == "name":
        value["nodes"][0]["name"] = "invented-name"
    elif mutation == "model":
        value["model_routes_enabled"] = True
    path.write_text("{" if mutation == "malformed" else json.dumps(value))
    with pytest.raises(PublicationValidationError):
        store.open_generation(reference)
    assert QueryService(store).execute(request_factory())["status"] == "unavailable"
