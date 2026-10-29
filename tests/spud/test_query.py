import json

import pytest

from knowitall_spud.query import (
    ARTIFACT_CONTRACT,
    ArtifactQueryService,
    ArtifactQueryValidationError,
    validate_artifact_request,
    validate_artifact_response,
)
from knowitall_spud.descriptor import DescriptorError, load_descriptor
from knowitall_spud.store import AdmissionStore

from conftest import (
    CITATION_INDEX_PATH,
    GRAPH_PATH,
    GRAPH_REPORT_PATH,
    SOURCE_EVIDENCE_PATH,
    digest_of,
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


def bound_value(bundle_root, value, *, source_coverage):
    value["source_binding"] = {
        "graph_digest": digest_of(bundle_root / GRAPH_PATH),
        "snapshot_id": "snapshot-1",
        "commit_sha": "1" * 40,
        "content_manifest_digest": digest_of(bundle_root / SOURCE_EVIDENCE_PATH),
        "content_manifest_path": SOURCE_EVIDENCE_PATH,
        "source_coverage": source_coverage,
    }
    return value


def test_declared_partial_source_coverage_is_never_answered_as_absence(tmp_path, make_bundle):
    evidence = {
        "snapshot_id": "snapshot-1",
        "commit": "1" * 40,
        "files": [
            {"path": "src/orders.py", "content_digest": "sha256:" + "2" * 64},
            {"path": "src/store.py", "content_digest": "sha256:" + "3" * 64},
        ],
    }
    bundle_root, value = make_bundle(citation_index=True, source_evidence=evidence)
    bundle = normalize_bundle_at(bundle_root, bound_value(bundle_root, value, source_coverage="partial"))
    assert bundle.limitations == ()
    assert bundle.source_coverage == "partial"
    store = AdmissionStore(tmp_path / "partial-coverage")
    store.admit(bundle)
    service = service_for(store)

    found = service.execute(request_for(relationships()))
    absent = service.execute(request_for(relationships(symbol_id="absent.symbol")))

    assert found["status"] == "partial"
    assert absent["status"] == "partial"
    assert reasons(absent) == {"partial_source_coverage"}
    assert {item["kind"] for item in absent["missing_evidence"]} == {"coverage"}
    validate_artifact_response(absent, expected_request=request_for(relationships(symbol_id="absent.symbol")))


def test_complete_declared_source_coverage_still_answers_ok(tmp_path, make_bundle):
    evidence = {
        "snapshot_id": "snapshot-1",
        "commit": "1" * 40,
        "files": [
            {"path": "src/orders.py", "content_digest": "sha256:" + "2" * 64},
            {"path": "src/store.py", "content_digest": "sha256:" + "3" * 64},
        ],
    }
    bundle_root, value = make_bundle(citation_index=True, source_evidence=evidence)
    bundle = normalize_bundle_at(bundle_root, bound_value(bundle_root, value, source_coverage="complete"))
    store = AdmissionStore(tmp_path / "complete-coverage")
    store.admit(bundle)

    response = service_for(store).execute(request_for(relationships()))

    assert response["status"] == "ok"
    assert response["missing_evidence"] == []


def test_invalid_request_envelope_validates_against_the_published_schema(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()

    response = service_for(store).execute({"contract": "other/v1"})

    assert response["status"] == "invalid_request"
    assert (response["request_id"], response["project_id"], response["repository_id"]) == (None, None, None)
    validate_artifact_response(response)


def test_paged_records_equal_the_unpaged_selection_in_order(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle(citation_index=True)
    query = {"kind": "artifact_path", "path": GRAPH_PATH}

    unpaged = service_for(store).execute(request_for(query))["records"]
    service = service_for(store, page_size=1)
    paged = []
    response = service.execute(request_for(query))
    paged.extend(response["records"])
    while response["continuation"] is not None:
        response = service.execute(request_for(query, continuation=response["continuation"]))
        paged.extend(response["records"])

    assert [record["record_id"] for record in paged] == [record["record_id"] for record in unpaged]


def test_declared_missing_reasons_are_constrained_to_the_published_vocabulary(make_bundle):
    _root, value = make_bundle()
    value["declared_missing"] = [["spud-out/json/analysis/inputs/graph-index.json", "no_such_reason"]]

    with pytest.raises(DescriptorError, match="declared_missing reason is not supported"):
        load_descriptor(value)


def test_pagination_survives_a_fresh_request_id_per_page(admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    service = service_for(store, page_size=1)
    query = {"kind": "artifact_path", "path": GRAPH_PATH}

    first = service.execute(request_for(query, request_id="page-1"))
    second = service.execute(request_for(query, request_id="page-2", continuation=first["continuation"]))

    assert second["status"] == "ok"
    assert second["request_id"] == "page-2"
    assert second["records"][0]["record_id"] != first["records"][0]["record_id"]


@pytest.mark.parametrize("identity", [123, "", "  ", None, {"id": "x"}])
def test_invalid_identities_are_echoed_as_null_in_the_invalid_request_envelope(admitted_bundle, identity):
    store, _bundle, _receipt = admitted_bundle()
    service = service_for(store)

    response = service.execute({"contract": ARTIFACT_CONTRACT, "request_id": identity})

    assert response["status"] == "invalid_request"
    assert response["request_id"] is None
    validate_artifact_response(response)
