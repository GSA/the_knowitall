from copy import deepcopy

import pytest

from knowitall_contract import (
    ContractValidationError,
    Coverage,
    GenerationRef,
    MissingEvidence,
    QueryStatus,
    SnapshotRef,
    SourceRange,
    validate_query_request,
    validate_query_response,
)
from test_schema_examples import load_example


def test_contract_records_are_frozen_and_keep_opaque_identity_exact():
    snapshot = SnapshotRef(
        project_id="Project-e01",
        repository_id="Repo-A",
        snapshot_id="Snap-1",
        commit="sha1:" + "1" * 40,
        content_manifest_digest="sha256:" + "a" * 64,
    )
    generation = GenerationRef(
        snapshot=snapshot,
        generation_id="Gen-1",
        artifact_digest="sha256:" + "d" * 64,
    )

    assert generation.snapshot.project_id == "Project-e01"
    assert generation.snapshot.repository_id != "repo-a"
    with pytest.raises(AttributeError):
        generation.generation_id = "other"


def test_source_range_is_one_based_half_open():
    with pytest.raises(ValueError, match="one-based"):
        SourceRange(start_line=0, start_column=1, end_line=1, end_column=2)
    with pytest.raises(ValueError, match="half-open"):
        SourceRange(start_line=2, start_column=3, end_line=2, end_column=3)

    assert SourceRange(2, 3, 2, 4).end_column == 4


def test_status_and_coverage_records_use_closed_vocabularies():
    assert QueryStatus.OK.value == "ok"
    assert Coverage("complete", "partial", "partial", ("parser failed",)).limitations
    assert MissingEvidence("parser", "src/bad.py", "syntax_error").scope == "src/bad.py"


def test_exact_selector_requires_exact_fields():
    request = load_example("exact-dependency-request.json")
    del request["selector"]["generation_id"]

    with pytest.raises(ContractValidationError, match="generation_id"):
        validate_query_request(request)


def test_current_selector_rejects_exact_fields():
    request = load_example("exact-dependency-request.json")
    request["selector"] = {
        "mode": "current",
        "snapshot_id": "snap-python-0001",
    }

    with pytest.raises(ContractValidationError, match="snapshot_id"):
        validate_query_request(request)


def test_response_range_end_must_follow_start():
    response = load_example("dependency-response.json")
    locator = response["evidence"][0]["locator"]
    locator["end"] = deepcopy(locator["start"])

    with pytest.raises(ContractValidationError, match="half-open"):
        validate_query_response(response)


def test_partial_response_requires_machine_readable_missing_evidence():
    response = load_example("dependency-response.json")
    response["status"] = "partial"
    response["coverage"]["relevant_scope"] = "partial"
    response["coverage"]["limitations"] = ["parser_error"]

    with pytest.raises(ContractValidationError, match="missing_evidence"):
        validate_query_response(response)


def test_partial_response_requires_coverage_limitations():
    response = load_example("dependency-response.json")
    response["status"] = "partial"
    response["coverage"]["relevant_scope"] = "partial"
    response["missing_evidence"] = [{"kind": "extraction", "scope": "src/orders.py", "reason": "parser_error"}]

    with pytest.raises(ContractValidationError, match="coverage.limitations"):
        validate_query_response(response)


def test_response_identity_must_exactly_match_request_identity_when_provided():
    request = load_example("exact-dependency-request.json")
    response = load_example("dependency-response.json")
    response["project_id"] = request["project_id"].upper()

    with pytest.raises(ContractValidationError, match="identity mismatch"):
        validate_query_response(response, expected_request=request)
