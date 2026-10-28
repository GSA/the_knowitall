from knowitall_query import QueryService


def test_complete_response_has_no_continuation(published_graph, request_factory):
    store, _ = published_graph()
    response = QueryService(store, page_size=2).execute(request_factory())

    assert response["truncated"] is False
    assert response["continuation"] is None


def test_truncation_and_next_page_are_explicit_and_deterministic(published_graph, request_factory):
    store, _ = published_graph(edge_count=3)
    service = QueryService(store, page_size=2)

    first = service.execute(request_factory())
    second = service.execute(request_factory(continuation=first["continuation"]))

    assert first["truncated"] is True
    assert [item["evidence_id"] for item in first["evidence"]] == ["calls-save-0", "calls-save-1"]
    assert [item["evidence_id"] for item in second["evidence"]] == ["calls-save-2"]
    assert second["truncated"] is False
    assert second["continuation"] is None


def test_altered_or_rebound_continuation_is_invalid(published_graph, request_factory):
    store, _ = published_graph(edge_count=2)
    service = QueryService(store, page_size=1)
    token = service.execute(request_factory())["continuation"]

    altered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert service.execute(request_factory(continuation=altered))["status"] == "invalid_request"
    assert service.execute(request_factory(request_id="request-2", continuation=token))["status"] == "invalid_request"
    assert service.execute(request_factory(symbol="store.save", continuation=token))["status"] == "invalid_request"
    assert QueryService(store, page_size=2).execute(request_factory(continuation=token))["status"] == "invalid_request"
