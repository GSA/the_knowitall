#!/usr/bin/env python3
"""Validate every checked-in knowitall.code-context/v1 example."""

import json
from pathlib import Path

from knowitall_contract import validate_manifest, validate_query_request, validate_query_response


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "knowitall.code-context" / "v1"
VALIDATORS = {
    "clean-manifest.json": validate_manifest,
    "exact-dependency-request.json": validate_query_request,
    "dependency-response.json": validate_query_response,
    "partial-response.json": validate_query_response,
}


def main() -> None:
    actual = {path.name for path in EXAMPLES.glob("*.json")}
    expected = set(VALIDATORS)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise SystemExit(f"example inventory mismatch: missing={missing}, unexpected={unexpected}")
    for name, validator in sorted(VALIDATORS.items()):
        value = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
        validator(value)
        print(f"validated {name}")


if __name__ == "__main__":
    main()
