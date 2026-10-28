from knowitall_query import QueryService


def exact(generation, freshness="allow_historical"):
    return {"mode": "exact", "snapshot_id": generation.snapshot.snapshot_id, "generation_id": generation.generation_id, "freshness": freshness}


def test_current_resolves_and_echoes_immutable_identity(published_graph, request_factory):
    store, generation = published_graph()
    response = QueryService(store).execute(request_factory())

    assert response["status"] == "ok"
    assert response["resolved"] == {
        "snapshot_id": generation.snapshot.snapshot_id,
        "commit": generation.snapshot.commit,
        "content_manifest_digest": generation.snapshot.content_manifest_digest,
        "generation_id": generation.generation_id,
        "artifact_digest": generation.artifact_digest,
    }


def test_exact_historical_is_allowed_but_require_current_is_stale(published_graph, request_factory):
    store, first = published_graph()
    _, second = published_graph(partial=True)
    assert store.resolve_current("project-a", "repo-a").generation_id == second.generation_id

    historical = QueryService(store).execute(request_factory(selector=exact(first)))
    stale = QueryService(store).execute(request_factory(selector=exact(first, "require_current")))

    assert historical["status"] == "ok"
    assert historical["resolved"]["generation_id"] == first.generation_id
    assert stale["status"] == "stale"
    assert stale["evidence"] == []


def test_missing_generation_or_repository_is_unavailable_without_fallback(published_graph, request_factory):
    store, generation = published_graph()
    missing_generation = dict(exact(generation), generation_id="gen-missing")

    unavailable = QueryService(store).execute(request_factory(selector=missing_generation))
    wrong_repository = QueryService(store).execute(request_factory(repository="repo-other"))

    assert unavailable["status"] == "unavailable"
    assert wrong_repository["status"] == "unavailable"
    assert unavailable["resolved"] is None
    assert wrong_repository["resolved"] is None


def test_invalid_contract_request_still_returns_v1_error_envelope(published_graph, request_factory):
    store, _ = published_graph()
    request = request_factory()
    request["contract"] = "unsupported/v9"

    response = QueryService(store).execute(request)

    assert response["contract"] == "knowitall.code-context/v1"
    assert response["status"] == "invalid_request"


def test_malformed_identity_values_cannot_break_error_packet(published_graph):
    store, _ = published_graph()

    response = QueryService(store).execute({"request_id": [], "project_id": "", "repository_id": None})

    assert response["status"] == "invalid_request"
    assert response["request_id"] == "invalid"
    assert response["project_id"] == "invalid"
    assert response["repository_id"] == "invalid"


def test_invalid_request_is_explicit_status(published_graph, request_factory):
    store, _ = published_graph()
    request = request_factory()
    request["selector"] = {"mode": "exact"}

    response = QueryService(store).execute(request)

    assert response["status"] == "invalid_request"
    assert response["resolved"] is None
