import json
from copy import deepcopy
from pathlib import Path

import pytest

from knowitall_contract import (
    ContractValidationError,
    validate_manifest,
    validate_query_request,
    validate_query_response,
)


EXAMPLES = Path(__file__).parents[2] / "examples" / "knowitall.code-context" / "v1"


def load_example(name: str) -> dict[str, object]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("filename", "validator"),
    [
        ("clean-manifest.json", validate_manifest),
        ("exact-dependency-request.json", validate_query_request),
        ("dependency-response.json", validate_query_response),
        ("partial-response.json", validate_query_response),
    ],
)
def test_checked_in_examples_validate(filename, validator):
    validator(load_example(filename))


def test_unknown_contract_fails_closed():
    request = load_example("exact-dependency-request.json")
    request["contract"] = "knowitall.code-context/v2"

    with pytest.raises(ContractValidationError, match=r"^contract:"):
        validate_query_request(request)


@pytest.mark.parametrize("missing", ["project_id", "repository_id"])
def test_request_requires_explicit_identity(missing):
    request = load_example("exact-dependency-request.json")
    del request[missing]

    with pytest.raises(ContractValidationError, match=missing):
        validate_query_request(request)


def test_required_identity_cannot_be_null():
    request = load_example("exact-dependency-request.json")
    request["repository_id"] = None

    with pytest.raises(ContractValidationError, match="repository_id"):
        validate_query_request(request)


@pytest.mark.parametrize("path", ["/src/orders.py", "src/../orders.py"])
def test_manifest_rejects_unsafe_paths(path):
    manifest = load_example("clean-manifest.json")
    manifest["scope"]["included"][0]["path"] = path

    with pytest.raises(ContractValidationError, match="path"):
        validate_manifest(manifest)


def test_response_rejects_zero_based_locator():
    response = load_example("dependency-response.json")
    response["evidence"][0]["locator"]["start"]["line"] = 0

    with pytest.raises(ContractValidationError, match="line"):
        validate_query_response(response)


def test_manifest_rejects_invalid_digest():
    manifest = load_example("clean-manifest.json")
    manifest["source"]["content_manifest_digest"] = "abc123"

    with pytest.raises(ContractValidationError, match="content_manifest_digest"):
        validate_manifest(manifest)


def test_manifest_rejects_duplicate_final_scope_path():
    manifest = load_example("clean-manifest.json")
    manifest["scope"]["failed"] = [
        {"path": manifest["scope"]["included"][0]["path"], "reason": "parser_failed"}
    ]

    with pytest.raises(ContractValidationError, match="scope paths"):
        validate_manifest(manifest)
