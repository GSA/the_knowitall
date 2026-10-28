from knowitall_query import QueryService


def test_known_dependency_returns_deterministic_source_bound_evidence(published_graph, request_factory):
    store, _ = published_graph()

    response = QueryService(store).execute(request_factory())

    assert response["status"] == "ok"
    assert len(response["evidence"]) == 1
    evidence = response["evidence"][0]
    assert evidence["evidence_id"] == "calls-save-0"
    assert evidence["grade"] == "deterministic_extraction"
    assert evidence["subject"]["symbol_id"] == "orders.submit"
    assert evidence["object"]["symbol_id"] == "store.save"
    assert evidence["locator"]["start"] == {"line": 5, "column": 1}
    assert evidence["locator"]["end"] == {"line": 6, "column": 1}


def test_authoritative_absence_is_not_found_only_with_complete_coverage(published_graph, request_factory):
    store, _ = published_graph()
    response = QueryService(store).execute(request_factory(symbol="missing"))

    assert response["status"] == "not_found"
    assert response["missing_evidence"] == []


def test_partial_coverage_never_claims_authoritative_absence(published_graph, request_factory):
    store, _ = published_graph(partial=True)
    response = QueryService(store).execute(request_factory(symbol="missing"))

    assert response["status"] == "partial"
    assert response["coverage"]["relevant_scope"] == "partial"
    assert response["missing_evidence"] == [{"kind": "extraction", "scope": "src/store.py", "reason": "parser_error"}]


def test_existing_symbol_with_no_matching_relationship_is_authoritative_empty(published_graph, request_factory):
    store, _ = published_graph()
    response = QueryService(store).execute(request_factory(symbol="store.save", direction="outgoing"))

    assert response["status"] == "ok"
    assert response["evidence"] == []
