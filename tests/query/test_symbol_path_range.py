from knowitall_contract import validate_query_request, validate_query_response
from knowitall_query import QueryService


def execute(published_graph, request_factory, query, **graph_options):
    store, _ = published_graph(**graph_options)
    request = request_factory(query=query, repository=graph_options.get("repository", "repo-a"))
    validate_query_request(request)
    response = QueryService(store).execute(request)
    validate_query_response(response, expected_request=request)
    return response


def test_exact_symbol_lookup_returns_definition_evidence(published_graph, request_factory):
    response = execute(published_graph, request_factory, {"kind": "symbol", "name": "save", "match": "exact"})

    assert response["status"] == "ok"
    assert response["evidence"][0]["kind"] == "definition"
    assert response["evidence"][0]["subject"] == response["evidence"][0]["object"] == {
        "symbol_id": "store.save", "name": "save"
    }


def test_partial_symbol_ambiguity_retains_missing_evidence(published_graph, request_factory):
    store, _ = published_graph(repository="partial-ambiguous", partial=True, duplicate_names=True)
    response = QueryService(store).execute(request_factory(
        repository="partial-ambiguous",
        query={"kind": "symbol", "name": "submit", "match": "exact"},
    ))

    assert response["status"] == "ambiguous"
    assert response["coverage"]["relevant_scope"] == "partial"
    assert response["missing_evidence"]


def test_ambiguity_candidates_are_bounded_and_continuable(published_graph, request_factory):
    store, _ = published_graph(repository="ambiguity-page", duplicate_names=True)
    service = QueryService(store, page_size=1, continuation_secret=b"a" * 32)
    request = request_factory(repository="ambiguity-page", query={"kind": "symbol", "name": "submit", "match": "exact"})

    first = service.execute(request)
    second = service.execute({**request, "continuation": first["continuation"]})

    assert first["status"] == second["status"] == "ambiguous"
    assert first["truncated"] is True
    assert second["truncated"] is False
    assert first["ambiguities"] + second["ambiguities"] == [
        {"symbol_id": "orders.submit", "name": "submit"},
        {"symbol_id": "other.submit", "name": "submit"},
    ]


def test_normalized_symbol_lookup_returns_ambiguity_candidates_without_selecting(published_graph, request_factory):
    response = execute(
        published_graph,
        request_factory,
        {"kind": "symbol", "name": " SUBMIT ", "match": "normalized"},
        duplicate_names=True,
    )

    assert response["status"] == "ambiguous"
    assert response["evidence"] == []
    assert response["ambiguities"] == [
        {"symbol_id": "orders.submit", "name": "submit"},
        {"symbol_id": "other.submit", "name": "submit"},
    ]


def test_path_query_returns_only_evidence_on_exact_path(published_graph, request_factory):
    response = execute(published_graph, request_factory, {"kind": "path", "path": "src/orders.py"})

    assert response["status"] == "ok"
    assert response["evidence"]
    assert {item["locator"]["path"] for item in response["evidence"]} == {"src/orders.py"}


def test_path_query_paginates_and_continuation_cannot_be_rebound(published_graph, request_factory):
    store, _ = published_graph()
    service = QueryService(store, page_size=1, continuation_secret=b"stable-test-secret")
    query = {"kind": "path", "path": "src/orders.py"}
    first_request = request_factory(query=query)
    first = service.execute(first_request)

    assert first["truncated"] is True
    second = service.execute(request_factory(query=query, continuation=first["continuation"]))
    rebound = service.execute(request_factory(query={"kind": "path", "path": "src/store.py"}, continuation=first["continuation"]))
    assert second["status"] == "ok"
    assert rebound["status"] == "invalid_request"


def test_source_range_query_returns_intersecting_nodes_and_edges(published_graph, request_factory):
    response = execute(published_graph, request_factory, {
        "kind": "source_range",
        "path": "src/orders.py",
        "start": {"line": 5, "column": 1},
        "end": {"line": 6, "column": 1},
    })

    assert response["status"] == "ok"
    assert {item["kind"] for item in response["evidence"]} == {"definition", "calls"}


def test_path_query_ignores_unrelated_extraction_failure(published_graph, request_factory):
    response = execute(
        published_graph,
        request_factory,
        {"kind": "path", "path": "src/orders.py"},
        repository="partial",
        partial=True,
    )

    assert response["status"] == "ok"
    assert response["missing_evidence"] == []


def test_missing_path_is_authoritative_when_failures_are_unrelated(published_graph, request_factory):
    complete = execute(published_graph, request_factory, {"kind": "path", "path": "src/missing.py"})
    globally_partial = execute(published_graph, request_factory, {"kind": "path", "path": "src/missing.py"}, repository="partial", partial=True)

    assert complete["status"] == "not_found"
    assert globally_partial["status"] == "not_found"
    assert globally_partial["coverage"]["extraction"] == "partial"
    assert globally_partial["coverage"]["relevant_scope"] == "complete"
    assert globally_partial["missing_evidence"] == []
