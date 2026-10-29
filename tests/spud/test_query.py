import json

import pytest

from knowitall_spud.query import (
    ARTIFACT_CONTRACT,
    ArtifactQueryService,
    ArtifactQueryValidationError,
    validate_artifact_request,
    validate_artifact_response,
)
from knowitall_spud.store import AdmissionStore

from conftest import (
    CITATION_INDEX_PATH,
    GRAPH_PATH,
    GRAPH_REPORT_PATH,
    normalize_bundle_at,
)


SECRET = b"spud-artifact-test-secret"


def request_for(query, *, bundle_id="bundle-1", project="project-a", repository="repo-a", request_id="req-1", **extra):
    value = {
        "contract": ARTIFACT_CONTRACT,
        "request_id": request_id,
        "project_id": project,
        "repository_id": repository,
        "selector": {"mode": "bundle", "bundle_id": bundle_id},
        "query": query,
    }
    value.update(extra)
    return value


def relationships(symbol_id="orders.submit", direction="outgoing", relations=("calls",)):
    return {"kind": "relationships", "symbol_id": symbol_id, "direction": direction, "relations": list(relations)}


def service_for(store, page_size=50):
    return ArtifactQueryService(store, page_size=page_size, continuation_secret=SECRET)


def reasons(response):
    return {item["reason"] for item in response["missing_evidence"]}


def test_relationship_query_returns_attributed_graph_records(admitted_bundle):
    store, bundle, receipt = admitted_bundle()
    response = service_for(store).execute(request_for(relationships()))

    assert response["status"] == "ok"
    assert response["contract"] == ARTIFACT_CONTRACT
    assert response["request_id"] == "req-1"
    assert response["resolved"] == {
        "bundle_id": "bundle-1",
        "receipt_digest": receipt.receipt_digest,
        "reader_profile": "spud-reader/v1",
        "revision_binding": bundle.revision_binding,
        "bound_snapshot": None,
    }
    assert len(response["records"]) == 1
    record = response["records"][0]
    assert (record["kind"], record["grade"]) == ("graph_relationship", "recorded_artifact")
    assert (record["subject"], record["relation"], record["object"]) == ("orders.submit", "calls", "store.save")
    assert record["attribution"]["confidence"] == "EXTRACTED"
    assert record["source_reference"] == {"path": "src/orders.py", "start_line": 5, "end_line": 6}
    assert record["locator"]["artifact_path"] == GRAPH_PATH
    assert record["locator"]["pointer"] == "/edges/0"
    assert response["admission"]["artifacts"]
    assert response["truncated"] is False
    assert response["continuation"] is None


def test_symbol_query_matches_exact_and_normalized(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    service = service_for(store)

    exact = service.execute(request_for({"kind": "symbol", "name": "orders.submit", "match": "exact"}))
    assert exact["status"] == "ok"
    assert [record["name"] for record in exact["records"]] == ["orders.submit"]

    missed = service.execute(request_for({"kind": "symbol", "name": "Orders.Submit", "match": "exact"}))
    assert missed["status"] == "not_found"
    assert missed["records"] == []

    normalized = service.execute(request_for({"kind": "symbol", "name": " Orders.Submit ", "match": "normalized"}))
    assert normalized["status"] == "ok"
    assert [record["name"] for record in normalized["records"]] == ["orders.submit"]


def test_artifact_path_query_returns_records_for_that_artifact(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    response = service_for(store).execute(request_for({"kind": "artifact_path", "path": GRAPH_PATH}))

    assert response["status"] == "ok"
    assert {record["locator"]["artifact_path"] for record in response["records"]} == {GRAPH_PATH}
    assert {record["kind"] for record in response["records"]} == {"graph_symbol", "graph_relationship"}


def test_narrative_search_returns_passage_with_line_locator(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    response = service_for(store).execute(request_for({"kind": "narrative_search", "text": "persistence boundary"}))

    assert response["status"] == "ok"
    assert len(response["records"]) == 1
    record = response["records"][0]
    assert (record["kind"], record["grade"]) == ("narrative_passage", "generated_narrative")
    assert record["locator"]["start_line"] == 3
    assert record["locator"]["end_line"] == 5
    assert record["locator"]["pointer"] is None
    assert "persistence boundary" in record["text"]
    assert record["source_reference"] is None


def test_partial_bundle_reports_limitations_and_partial_status(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle(report=False)
    response = service_for(store).execute(request_for(relationships()))

    assert response["status"] == "partial"
    assert response["records"]
    assert "missing_graph_report" in reasons(response)
    assert any(reason == "missing_graph_report" for _scope, reason in [tuple(item) for item in response["admission"]["limitations"]])


def test_citation_only_bundle_does_not_report_empty_relationships(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle(graph=False, report=False, citation_index=True)
    response = service_for(store).execute(request_for(relationships()))

    assert response["status"] == "partial"
    assert response["records"] == []
    assert "missing_graph" in reasons(response)

    citations = service_for(store).execute(request_for({"kind": "artifact_path", "path": CITATION_INDEX_PATH}))
    assert {record["kind"] for record in citations["records"]} == {"citation_entry"}
    assert {record["grade"] for record in citations["records"]} == {"recorded_citation"}
    assert all(record["relation"] is None for record in citations["records"])


def test_no_match_in_complete_bundle_is_not_found(admitted_bundle):
    store, bundle, _receipt = admitted_bundle(citation_index=True)
    assert bundle.artifact_completeness == "complete"

    response = service_for(store).execute(request_for(relationships(symbol_id="absent.symbol")))

    assert response["status"] == "not_found"
    assert response["records"] == []
    assert response["missing_evidence"] == []


def test_unknown_bundle_is_unavailable(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    response = service_for(store).execute(request_for(relationships(), bundle_id="bundle-absent"))

    assert response["status"] == "unavailable"
    assert response["records"] == []
    assert response["resolved"] is None


def test_cross_project_and_repository_isolation(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    service = service_for(store)

    assert service.execute(request_for(relationships(), project="project-b"))["status"] == "unavailable"
    assert service.execute(request_for(relationships(), repository="repo-b"))["status"] == "unavailable"


def test_pagination_is_visible_and_continuation_resumes(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    service = service_for(store, page_size=1)
    query = {"kind": "artifact_path", "path": GRAPH_PATH}

    first = service.execute(request_for(query))
    assert first["truncated"] is True
    assert first["continuation"]
    assert len(first["records"]) == 1

    second = service.execute(request_for(query, continuation=first["continuation"]))
    assert second["truncated"] is True
    assert len(second["records"]) == 1
    assert second["records"][0]["record_id"] != first["records"][0]["record_id"]

    third = service.execute(request_for(query, continuation=second["continuation"]))
    assert third["truncated"] is False
    assert third["continuation"] is None


def test_continuation_bound_to_bundle_query_and_page_size(admitted_bundle, make_bundle):
    store, _bundle, _receipt = admitted_bundle()
    other_root, other_value = make_bundle(bundle_id="bundle-2")
    store.admit(normalize_bundle_at(other_root, other_value))
    query = {"kind": "artifact_path", "path": GRAPH_PATH}
    token = service_for(store, page_size=1).execute(request_for(query))["continuation"]

    rebound_bundle = service_for(store, page_size=1).execute(
        request_for(query, bundle_id="bundle-2", continuation=token)
    )
    rebound_query = service_for(store, page_size=1).execute(
        request_for(relationships(), continuation=token)
    )
    rebound_size = service_for(store, page_size=2).execute(request_for(query, continuation=token))
    altered = service_for(store, page_size=1).execute(request_for(query, continuation="x" + token[1:]))

    assert rebound_bundle["status"] == "invalid_request"
    assert rebound_query["status"] == "invalid_request"
    assert rebound_size["status"] == "invalid_request"
    assert altered["status"] == "invalid_request"


def test_malformed_request_is_invalid_request(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    service = service_for(store)

    assert service.execute({"contract": "other/v1"})["status"] == "invalid_request"
    assert service.execute(request_for({"kind": "unsupported"}))["status"] == "invalid_request"
    assert service.execute(request_for({"kind": "artifact_path", "path": "../escape.md"}))["status"] == "invalid_request"
    broken = request_for(relationships())
    broken["selector"] = {"mode": "current"}
    assert service.execute(broken)["status"] == "invalid_request"

    with pytest.raises(ArtifactQueryValidationError):
        validate_artifact_request({"contract": ARTIFACT_CONTRACT})


def test_responses_validate_against_the_v1_envelope_schema(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle(citation_index=True)
    service = service_for(store)
    queries = [
        relationships(),
        {"kind": "symbol", "name": "orders.submit", "match": "exact"},
        {"kind": "artifact_path", "path": GRAPH_REPORT_PATH},
        {"kind": "narrative_search", "text": "orders"},
    ]
    for query in queries:
        request = request_for(query)
        validate_artifact_request(request)
        response = service.execute(request)
        validate_artifact_response(response, expected_request=request)
        json.dumps(response)

    with pytest.raises(ArtifactQueryValidationError, match="identity mismatch"):
        validate_artifact_response(service.execute(request_for(relationships())), expected_request=request_for(relationships(), request_id="other"))


def test_revision_binding_is_visible_in_every_response(admitted_bundle, make_bundle, tmp_path):
    unknown_store, unknown_bundle, _ = admitted_bundle(
        store=AdmissionStore(tmp_path / "unknown"), run_manifest=False, okf_manifest=False
    )
    assert unknown_bundle.revision_binding == "unknown"
    response = service_for(unknown_store).execute(request_for(relationships()))
    assert response["resolved"]["revision_binding"] == "unknown"
    assert response["resolved"]["bound_snapshot"] is None

    asserted_store, asserted_bundle, _ = admitted_bundle(store=AdmissionStore(tmp_path / "asserted"))
    assert asserted_bundle.revision_binding == "asserted"
    asserted = service_for(asserted_store).execute(request_for(relationships()))
    assert asserted["resolved"]["revision_binding"] == "asserted"
    assert asserted["resolved"]["bound_snapshot"] is None
