#!/usr/bin/env python3
"""Validate every checked-in contract example against its versioned schema."""

import json
from pathlib import Path

from knowitall_contract import validate_manifest, validate_query_request, validate_query_response
from knowitall_spud.query import validate_artifact_request, validate_artifact_response


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
SUITES = {
    "knowitall.code-context/v1": {
        "clean-manifest.json": validate_manifest,
        "exact-dependency-request.json": validate_query_request,
        "dependency-response.json": validate_query_response,
        "partial-response.json": validate_query_response,
    },
    "knowitall.spud-artifacts/v1": {
        "graph-relationship-request.json": validate_artifact_request,
        "graph-relationship-response.json": validate_artifact_response,
        "partial-citation-response.json": validate_artifact_response,
    },
}


def main() -> None:
    for contract, validators in sorted(SUITES.items()):
        directory = EXAMPLES / contract
        actual = {path.name for path in directory.glob("*.json")}
        expected = set(validators)
        if actual != expected:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            raise SystemExit(f"{contract} example inventory mismatch: missing={missing}, unexpected={unexpected}")
        for name, validator in sorted(validators.items()):
            value = json.loads((directory / name).read_text(encoding="utf-8"))
            validator(value)
            print(f"validated {contract}/{name}")


if __name__ == "__main__":
    main()
