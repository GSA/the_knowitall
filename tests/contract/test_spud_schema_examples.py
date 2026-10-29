import json
from pathlib import Path

import pytest

from knowitall_spud.query import validate_artifact_request, validate_artifact_response


EXAMPLES = Path(__file__).parents[2] / "examples" / "knowitall.spud-artifacts" / "v1"


@pytest.mark.parametrize(
    ("filename", "validator"),
    [
        ("graph-relationship-request.json", validate_artifact_request),
        ("graph-relationship-response.json", validate_artifact_response),
        ("partial-citation-response.json", validate_artifact_response),
    ],
)
def test_checked_in_spud_examples_validate(filename, validator):
    validator(json.loads((EXAMPLES / filename).read_text(encoding="utf-8")))


def test_every_checked_in_spud_example_is_covered():
    covered = {
        "graph-relationship-request.json",
        "graph-relationship-response.json",
        "partial-citation-response.json",
    }
    assert {path.name for path in EXAMPLES.glob("*.json")} == covered
