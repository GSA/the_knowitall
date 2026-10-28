import os
from dataclasses import asdict
from collections.abc import Mapping

from knowitall_contract import ContractValidationError, validate_query_request, validate_query_response
from knowitall_publication import PublicationStore

from .continuation import InvalidContinuation, issue_token, read_token
from .status import empty_response


def _resolved(reference):
    snapshot = reference.snapshot
    return {
        "snapshot_id": snapshot.snapshot_id,
        "commit": snapshot.commit,
        "content_manifest_digest": snapshot.content_manifest_digest,
        "generation_id": reference.generation_id,
        "artifact_digest": reference.artifact_digest,
    }


def _coverage(generation):
    value = asdict(generation.coverage)
    value["limitations"] = list(value["limitations"])
    return value


def _evidence(edge, nodes):
    locator = edge.source_range
    return {
        "evidence_id": edge.evidence_id,
        "grade": "deterministic_extraction",
        "kind": edge.kind,
        "subject": {"symbol_id": edge.source, "name": nodes[edge.source].name},
        "object": {"symbol_id": edge.target, "name": nodes[edge.target].name},
        "locator": {
            "path": edge.path,
            "start": {"line": locator.start_line, "column": locator.start_column},
            "end": {"line": locator.end_line, "column": locator.end_column},
            "content_digest": edge.content_digest,
        },
    }


class QueryService:
    def __init__(self, store: PublicationStore, page_size: int = 100, *, continuation_secret: bytes | None = None):
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            raise ValueError("page_size must be a positive integer")
        self.store = store
        self.page_size = page_size
        self.secret = continuation_secret or os.urandom(32)

    def _reference(self, request):
        selector = request["selector"]
        project, repository = request["project_id"], request["repository_id"]
        if selector["mode"] == "current":
            return self.store.resolve_current(project, repository), False
        reference = self.store.resolve_exact(project, repository, selector["snapshot_id"], selector["generation_id"])
        if selector["freshness"] == "require_current":
            try:
                current = self.store.resolve_current(project, repository)
            except KeyError:
                return reference, True
            return reference, current != reference
        return reference, False

    def execute(self, request: Mapping[str, object]) -> dict[str, object]:
        try:
            validate_query_request(request)
        except (ContractValidationError, TypeError):
            return empty_response(request, "invalid_request")
        try:
            reference, stale = self._reference(request)
            generation = self.store.open_generation(reference)
        except KeyError:
            return empty_response(request, "unavailable")
        resolved = _resolved(reference)
        coverage = _coverage(generation)
        if stale:
            response = empty_response(request, "stale", resolved=resolved, coverage=coverage)
            validate_query_response(response, expected_request=request)
            return response
        try:
            offset = read_token(request["continuation"], request, reference.generation_id, self.page_size, self.secret) if "continuation" in request else 0
        except InvalidContinuation:
            return empty_response(request, "invalid_request")
        query = request["query"]
        nodes = {node.symbol_id: node for node in generation.nodes}
        symbol_id = query["symbol_id"]
        if symbol_id not in nodes:
            status = "not_found" if generation.coverage.relevant_scope == "complete" else "partial"
            response = empty_response(request, status, resolved=resolved, coverage=coverage)
            if status == "partial":
                response["missing_evidence"] = [{"kind": "extraction", "scope": path, "reason": reason} for path, reason in generation.failed_files]
            validate_query_response(response, expected_request=request)
            return response
        kinds = set(query["relationship_kinds"])
        if query["direction"] == "outgoing":
            edges = [edge for edge in generation.edges if edge.source == symbol_id and edge.kind in kinds]
        else:
            edges = [edge for edge in generation.edges if edge.target == symbol_id and edge.kind in kinds]
        edges.sort(key=lambda edge: (edge.kind, edge.path, edge.source_range.start_line, edge.source_range.start_column, edge.evidence_id))
        page = edges[offset:offset + self.page_size]
        next_offset = offset + len(page)
        truncated = next_offset < len(edges)
        response = empty_response(request, "partial" if generation.state == "partial" else "ok", resolved=resolved, coverage=coverage)
        response["evidence"] = [_evidence(edge, nodes) for edge in page]
        response["missing_evidence"] = [{"kind": "extraction", "scope": path, "reason": reason} for path, reason in generation.failed_files]
        response["truncated"] = truncated
        response["continuation"] = issue_token(request, reference.generation_id, self.page_size, next_offset, self.secret) if truncated else None
        validate_query_response(response, expected_request=request)
        return response
