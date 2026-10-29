import json

import pytest

from knowitall_publication import PublicationStore, PublicationValidationError
from knowitall_query import QueryService


@pytest.mark.parametrize("payload", [b"not-json", b"{}", b"[]", b'{"snapshot":null}'])
def test_corrupt_current_pointer_is_unavailable_not_exception(generation_factory, tmp_path, payload):
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path)
    store.publish(store.stage(generation))
    next((tmp_path / "current").iterdir()).write_bytes(payload)
    with pytest.raises(PublicationValidationError):
        store.resolve_current("project-a", "repo-a")
    request = {"contract": "knowitall.code-context/v1", "request_id": "q", "project_id": "project-a", "repository_id": "repo-a", "selector": {"mode": "current"}, "query": {"kind": "symbol", "name": "absent", "match": "exact"}}
    assert QueryService(store).execute(request)["status"] == "unavailable"
