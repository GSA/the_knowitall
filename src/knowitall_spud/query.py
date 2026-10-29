"""Bundle-scoped queries over admitted SPUD artifacts.

Every response is an explicit `knowitall.spud-artifacts/v1` envelope: it names
the bundle and receipt it was answered from, the reader profile that read the
artifacts, the revision-binding status, and the admission limitations. Records
keep their evidence grade, so a citation or a generated narrative passage is
never presented as an extracted relationship.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from knowitall_query.continuation import InvalidContinuation, issue_token, read_token

from .records import ArtifactRecord, NormalizedBundle
from .store import AdmissionStore, AdmissionValidationError


ARTIFACT_CONTRACT = "knowitall.spud-artifacts/v1"

_PACKAGED_SCHEMA_ROOT = files("knowitall_spud").joinpath("schemas")
_SOURCE_SCHEMA_ROOT = Path(__file__).parents[2] / "schemas" / ARTIFACT_CONTRACT

_BINDING_REASONS = frozenset({"unverified_source_binding", "unbound_graph_source_files", "missing_bound_graph"})
_PROVENANCE_REASONS = frozenset(
    {"unknown_generator_version", "skipped_uploads", "unreadable_manifest_fields", "missing_okf_manifest", "missing_run_manifest"}
)

_QUERY_KINDS = ("symbol", "relationships", "artifact_path", "narrative_search")


class ArtifactQueryValidationError(ValueError):
    """A stable, caller-safe artifact-envelope validation failure."""


def _schema_error(error: Any) -> ArtifactQueryValidationError:
    path = ".".join(str(part) for part in error.absolute_path) or "document"
    return ArtifactQueryValidationError(f"{path}: {error.message}")


def _validate_schema(value: Mapping[str, object], filename: str) -> None:
    packaged = _PACKAGED_SCHEMA_ROOT.joinpath(filename)
    schema_path = packaged if packaged.is_file() else _SOURCE_SCHEMA_ROOT / filename
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        raise _schema_error(errors[0])


def validate_artifact_request(value: Mapping[str, object]) -> None:
    if not isinstance(value, Mapping):
        raise ArtifactQueryValidationError("document: request must be a mapping")
    _validate_schema(value, "artifact-query-request.schema.json")


def validate_artifact_response(
    value: Mapping[str, object], *, expected_request: Mapping[str, object] | None = None
) -> None:
    if not isinstance(value, Mapping):
        raise ArtifactQueryValidationError("document: response must be a mapping")
    _validate_schema(value, "artifact-query-response.schema.json")
    if value["status"] == "partial":
        if not value["missing_evidence"]:
            raise ArtifactQueryValidationError("missing_evidence: required for partial status")
        if not value["admission"]["limitations"]:
            raise ArtifactQueryValidationError("admission.limitations: required for partial status")
    if value["status"] in {"ok", "partial", "not_found"} and value["resolved"] is None:
        raise ArtifactQueryValidationError("resolved: required unless the bundle is unavailable")
    if expected_request is not None:
        for identity in ("contract", "request_id", "project_id", "repository_id"):
            if value[identity] != expected_request[identity]:
                raise ArtifactQueryValidationError(f"{identity}: identity mismatch with request")


def _missing_evidence(limitations: tuple[tuple[str, str], ...]) -> list[dict[str, str]]:
    found = []
    for scope, reason in limitations:
        if reason in _BINDING_REASONS:
            kind = "binding"
        elif reason in _PROVENANCE_REASONS:
            kind = "provenance"
        else:
            kind = "artifact"
        found.append({"kind": kind, "scope": scope, "reason": reason})
    return sorted(found, key=lambda item: (item["kind"], item["scope"], item["reason"]))


def _record_payload(record: ArtifactRecord) -> dict[str, object]:
    value = asdict(record)
    value["locator"] = asdict(record.locator)
    value["source_reference"] = asdict(record.source_reference) if record.source_reference is not None else None
    value["attribution"] = dict(record.attribution)
    return value


def _admission(bundle: NormalizedBundle) -> dict[str, object]:
    return {
        "artifacts": [
            {"role": item.role, "path": item.path, "content_digest": item.content_digest}
            for item in bundle.artifacts
        ],
        "source_coverage": bundle.source_coverage,
        "limitations": [list(item) for item in bundle.limitations],
    }


def _envelope(request: Mapping[str, object], status: str) -> dict[str, object]:
    return {
        "contract": ARTIFACT_CONTRACT,
        "request_id": request.get("request_id") if isinstance(request, Mapping) else None,
        "project_id": request.get("project_id") if isinstance(request, Mapping) else None,
        "repository_id": request.get("repository_id") if isinstance(request, Mapping) else None,
        "resolved": None,
        "status": status,
        "admission": {"artifacts": [], "source_coverage": "unknown", "limitations": []},
        "records": [],
        "missing_evidence": [],
        "truncated": False,
        "continuation": None,
    }


class ArtifactQueryService:
    def __init__(self, store: AdmissionStore, page_size: int = 50, *, continuation_secret: bytes | None = None):
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            raise ValueError("page_size must be a positive integer")
        self.store = store
        self.page_size = page_size
        self.secret = continuation_secret or os.urandom(32)

    def _selected(self, query: Mapping[str, object], bundle: NormalizedBundle) -> list[ArtifactRecord]:
        kind = query["kind"]
        if kind == "relationships":
            symbol_id, relations = query["symbol_id"], set(query["relations"])
            field = "subject" if query["direction"] == "outgoing" else "object"
            return [
                record
                for record in bundle.records
                if record.kind == "graph_relationship"
                and getattr(record, field) == symbol_id
                and record.relation in relations
            ]
        if kind == "symbol":
            wanted = query["name"]
            symbols = [record for record in bundle.records if record.kind == "graph_symbol"]
            if query["match"] == "normalized":
                wanted = wanted.strip().casefold()
                return [record for record in symbols if record.name.strip().casefold() == wanted]
            return [record for record in symbols if record.name == wanted]
        if kind == "artifact_path":
            path = query["path"]
            return [record for record in bundle.records if record.locator.artifact_path == path]
        text = query["text"].casefold()
        return [
            record
            for record in bundle.records
            if record.kind == "narrative_passage" and record.text is not None and text in record.text.casefold()
        ]

    def execute(self, request: Mapping[str, object]) -> dict[str, object]:
        try:
            validate_artifact_request(request)
        except (ArtifactQueryValidationError, TypeError):
            return _envelope(request if isinstance(request, Mapping) else {}, "invalid_request")
        selector = request["selector"]
        try:
            bundle, receipt = self.store.open_bundle(
                request["project_id"], request["repository_id"], selector["bundle_id"]
            )
        except (KeyError, AdmissionValidationError):
            return _envelope(request, "unavailable")
        try:
            offset = (
                read_token(request["continuation"], request, receipt.receipt_digest, self.page_size, self.secret)
                if "continuation" in request
                else 0
            )
        except InvalidContinuation:
            return _envelope(request, "invalid_request")

        selected = sorted(
            self._selected(request["query"], bundle),
            key=lambda record: (
                record.kind,
                record.locator.artifact_path,
                record.locator.start_line or 0,
                record.record_id,
            ),
        )
        missing = _missing_evidence(bundle.limitations)
        if missing:
            status = "partial"
        elif selected:
            status = "ok"
        else:
            status = "not_found"
        page = selected[offset : offset + self.page_size]
        next_offset = offset + len(page)
        truncated = next_offset < len(selected)

        response = _envelope(request, status)
        response["resolved"] = {
            "bundle_id": bundle.bundle_id,
            "receipt_digest": receipt.receipt_digest,
            "reader_profile": bundle.reader_profile,
            "revision_binding": bundle.revision_binding,
            "bound_snapshot": dict(bundle.bound_snapshot) if bundle.bound_snapshot is not None else None,
        }
        response["admission"] = _admission(bundle)
        response["records"] = [_record_payload(record) for record in page]
        response["missing_evidence"] = missing
        response["truncated"] = truncated
        response["continuation"] = (
            issue_token(request, receipt.receipt_digest, self.page_size, next_offset, self.secret)
            if truncated
            else None
        )
        validate_artifact_response(response, expected_request=request)
        return response
