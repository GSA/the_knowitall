from knowitall_query import QueryService


def test_duplicate_names_do_not_override_exact_symbol_identity(published_graph, request_factory):
    store, _ = published_graph(duplicate_names=True)

    first = QueryService(store).execute(request_factory(symbol="orders.submit"))
    duplicate = QueryService(store).execute(request_factory(symbol="other.submit"))

    assert first["status"] == "ok"
    assert [item["evidence_id"] for item in first["evidence"]] == ["calls-save-0"]
    assert duplicate["status"] == "ok"
    assert duplicate["evidence"] == []
    assert first["ambiguities"] == duplicate["ambiguities"] == []


def test_same_symbol_id_in_two_repositories_never_cross_substitutes(published_graph, request_factory):
    store, first = published_graph(repository="repo-a")
    _, second = published_graph(repository="repo-b", partial=True)

    first_response = QueryService(store).execute(request_factory(repository="repo-a"))
    second_response = QueryService(store).execute(request_factory(repository="repo-b"))

    assert first_response["status"] == "ok"
    assert second_response["status"] == "partial"
    assert first_response["resolved"]["generation_id"] == first.generation_id
    assert second_response["resolved"]["generation_id"] == second.generation_id
