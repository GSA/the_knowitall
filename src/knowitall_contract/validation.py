from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .models import SourceRange


CONTRACT = "knowitall.code-context/v1"
_PACKAGED_SCHEMA_ROOT = files("knowitall_contract").joinpath("schemas")
_SOURCE_SCHEMA_ROOT = Path(__file__).parents[2] / "schemas" / CONTRACT


class ContractValidationError(ValueError):
    """A stable, caller-safe v1 validation failure."""


def _schema_error(error: Any) -> ContractValidationError:
    path = ".".join(str(part) for part in error.absolute_path) or "document"
    return ContractValidationError(f"{path}: {error.message}")


def _validate_schema(value: Mapping[str, object], filename: str) -> None:
    import json

    packaged = _PACKAGED_SCHEMA_ROOT.joinpath(filename)
    schema_path = packaged if packaged.is_file() else _SOURCE_SCHEMA_ROOT / filename
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        raise _schema_error(errors[0])


def _paths(scope: Mapping[str, object]) -> list[str]:
    result: list[str] = []
    for category in ("included", "excluded", "failed"):
        for entry in scope[category]:  # type: ignore[index, union-attr]
            result.append(entry["path"])
    return result


def validate_manifest(value: Mapping[str, object]) -> None:
    _validate_schema(value, "snapshot-manifest.schema.json")
    paths = _paths(value["scope"])  # type: ignore[arg-type]
    if len(paths) != len(set(paths)):
        raise ContractValidationError("scope paths: final included, excluded, and failed paths must be disjoint")


def validate_query_request(value: Mapping[str, object]) -> None:
    selector = value.get("selector")
    if isinstance(selector, Mapping) and selector.get("mode") == "exact":
        for field in ("snapshot_id", "generation_id", "freshness"):
            if field not in selector:
                raise ContractValidationError(f"selector.{field}: required for exact mode")
    _validate_schema(value, "query-request.schema.json")


def _validate_ranges(value: Mapping[str, object]) -> None:
    for index, evidence in enumerate(value["evidence"]):  # type: ignore[index, union-attr]
        locator = evidence.get("locator")
        if not locator:
            continue
        try:
            SourceRange(
                locator["start"]["line"],
                locator["start"]["column"],
                locator["end"]["line"],
                locator["end"]["column"],
            )
        except ValueError as error:
            raise ContractValidationError(f"evidence.{index}.locator: {error}") from error


def validate_query_response(
    value: Mapping[str, object], *, expected_request: Mapping[str, object] | None = None
) -> None:
    _validate_schema(value, "query-response.schema.json")
    _validate_ranges(value)
    if expected_request is not None:
        for identity in ("contract", "request_id", "project_id", "repository_id"):
            if value[identity] != expected_request[identity]:
                raise ContractValidationError(f"{identity}: identity mismatch with request")
