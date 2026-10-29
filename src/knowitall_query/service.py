import os
from collections.abc import Mapping
from dataclasses import asdict

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


def _locator(path, source_range, content_digest):
    return {
        "path": path,
        "start": {"line": source_range.start_line, "column": source_range.start_column},
        "end": {"line": source_range.end_line, "column": source_range.end_column},
        "content_digest": content_digest,
    }


def _edge_evidence(edge, nodes):
    return {
        "evidence_id": edge.evidence_id,
        "grade": "deterministic_extraction",
        "kind": edge.kind,
        "subject": {"symbol_id": edge.source, "name": nodes[edge.source].name},
        "object": {"symbol_id": edge.target, "name": nodes[edge.target].name},
        "locator": _locator(edge.path, edge.source_range, edge.content_digest),
    }


def _node_evidence(node):
    symbol = {"symbol_id": node.symbol_id, "name": node.name}
    return {
        "evidence_id": f"definition:{node.symbol_id}",
        "grade": "deterministic_extraction",
        "kind": "definition",
        "subject": symbol,
        "object": symbol,
        "locator": _locator(node.path, node.source_range, node.content_digest),
    }


def _missing(generation, query):
    missing = [
        *({"kind": "inventory", "scope": path, "reason": reason} for path, reason in generation.inventory_failures),
    ]
    kind = query["kind"]
    if kind in {"symbol", "dependencies"}:
        failed = generation.failed_files
        excluded = generation.exclusions
    elif kind in {"path", "source_range"}:
        wanted = query["path"]
        related = lambda path: wanted == path or wanted.startswith(path + "/") or path.startswith(wanted + "/")
        failed = ((path, reason) for path, reason in generation.failed_files if related(path))
        excluded = ((path, reason) for path, reason in generation.exclusions if related(path))
    else:
        failed = excluded = ()
    missing.extend({"kind": "extraction", "scope": path, "reason": reason} for path, reason in failed)
    missing.extend({"kind": "exclusion", "scope": path, "reason": reason} for path, reason in excluded)
    return missing


def _intersects(source_range, start, end):
    item_start = (source_range.start_line, source_range.start_column)
    item_end = (source_range.end_line, source_range.end_column)
    return item_start < end and start < item_end


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

    def _selected_evidence(self, query, generation, nodes):
        kind = query["kind"]
        if kind == "dependencies":
            symbol_id = query["symbol_id"]
            if symbol_id not in nodes:
                return None
            kinds = set(query["relationship_kinds"])
            if query["direction"] == "outgoing":
                edges = [edge for edge in generation.edges if edge.source == symbol_id and edge.kind in kinds]
            else:
                edges = [edge for edge in generation.edges if edge.target == symbol_id and edge.kind in kinds]
            return [_edge_evidence(edge, nodes) for edge in edges]
        if kind == "symbol":
            wanted = query["name"]
            if query["match"] == "normalized":
                wanted = wanted.strip().casefold()
                matched = [node for node in generation.nodes if node.name.strip().casefold() == wanted]
            else:
                matched = [node for node in generation.nodes if node.name == wanted]
            return [_node_evidence(node) for node in matched]
        if kind == "path":
            path = query["path"]
            return [
                *(_node_evidence(node) for node in generation.nodes if node.path == path),
                *(_edge_evidence(edge, nodes) for edge in generation.edges if edge.path == path),
            ]
        path = query["path"]
        start = (query["start"]["line"], query["start"]["column"])
        end = (query["end"]["line"], query["end"]["column"])
        return [
            *(_node_evidence(node) for node in generation.nodes if node.path == path and _intersects(node.source_range, start, end)),
            *(_edge_evidence(edge, nodes) for edge in generation.edges if edge.path == path and _intersects(edge.source_range, start, end)),
        ]

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
        resolved, coverage = _resolved(reference), _coverage(generation)
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
        selected = self._selected_evidence(query, generation, nodes)
        missing = _missing(generation, query)
        coverage["relevant_scope"] = "partial" if missing else "complete"
        if missing:
            coverage["limitations"] = sorted(set(coverage["limitations"]) | {item["reason"] for item in missing})
        if selected is None or not selected:
            status = "not_found" if coverage["relevant_scope"] == "complete" else "partial"
            if selected == [] and query["kind"] == "dependencies" and query["symbol_id"] in nodes:
                status = "ok" if not missing else "partial"
            response = empty_response(request, status, resolved=resolved, coverage=coverage)
            response["missing_evidence"] = missing
            validate_query_response(response, expected_request=request)
            return response
        selected.sort(key=lambda item: (item["locator"]["path"], item["locator"]["start"]["line"], item["locator"]["start"]["column"], item["kind"], item["evidence_id"]))
        if query["kind"] == "symbol" and len(selected) > 1:
            candidates = sorted((item["subject"] for item in selected), key=lambda item: item["symbol_id"])
            page = candidates[offset:offset + self.page_size]
            next_offset = offset + len(page)
            truncated = next_offset < len(candidates)
            response = empty_response(request, "ambiguous", resolved=resolved, coverage=coverage)
            response["ambiguities"] = page
            response["missing_evidence"] = missing
            response["truncated"] = truncated
            response["continuation"] = issue_token(request, reference.generation_id, self.page_size, next_offset, self.secret) if truncated else None
            validate_query_response(response, expected_request=request)
            return response
        page = selected[offset:offset + self.page_size]
        next_offset = offset + len(page)
        truncated = next_offset < len(selected)
        response = empty_response(request, "partial" if missing else "ok", resolved=resolved, coverage=coverage)
        response["evidence"] = page
        response["missing_evidence"] = missing
        response["truncated"] = truncated
        response["continuation"] = issue_token(request, reference.generation_id, self.page_size, next_offset, self.secret) if truncated else None
        validate_query_response(response, expected_request=request)
        return response
