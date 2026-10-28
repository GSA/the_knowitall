UNKNOWN_COVERAGE = {
    "inventory": "unknown",
    "extraction": "unknown",
    "relevant_scope": "unknown",
    "limitations": [],
}


def _identity(request, name):
    value = request.get(name)
    return value if isinstance(value, str) and value else "invalid"


def empty_response(request, status, *, resolved=None, coverage=None):
    return {
        "contract": "knowitall.code-context/v1",
        "request_id": _identity(request, "request_id"),
        "project_id": _identity(request, "project_id"),
        "repository_id": _identity(request, "repository_id"),
        "resolved": resolved,
        "status": status,
        "coverage": dict(coverage or UNKNOWN_COVERAGE),
        "evidence": [],
        "ambiguities": [],
        "missing_evidence": [],
        "truncated": False,
        "continuation": None,
    }
