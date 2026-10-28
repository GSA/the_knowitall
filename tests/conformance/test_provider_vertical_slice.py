import os
from pathlib import Path

import pytest

from knowitall_contract import validate_query_response
from knowitall_graphify import GraphifyConfig, executable_digest, extract_generation
from knowitall_publication import PublicationStore
from knowitall_query import QueryService
from knowitall_snapshot import SnapshotPolicy, create_snapshot


RUNTIME = os.environ.get("KNOWITALL_GRAPHIFY_RUNTIME")
pytestmark = pytest.mark.skipif(not RUNTIME, reason="verified pinned Graphify runtime not installed")


def graphify_config(tmp_path: Path) -> GraphifyConfig:
    interpreter = Path(RUNTIME) / "bin" / "python"
    package_root = Path(RUNTIME) / "lib" / "python3.14" / "site-packages"
    return GraphifyConfig(executable=interpreter, python_path=str(package_root), expected_executable_digest=executable_digest(interpreter))


@pytest.mark.parametrize(
    ("fixture", "source_name", "target_name", "line"),
    [
        ("python_service", "submit_order()", "save_order()", 5),
        ("typescript_client", "loadOrder()", "fetchOrder()", 4),
    ],
)
def test_real_engine_snapshot_publish_query_packet(make_repo, tmp_path, fixture, source_name, target_name, line):
    project_id, repository_id = "project-synthetic", f"repo-{fixture}"
    repo = make_repo(fixture)
    snapshot_root = tmp_path / "snapshots"
    snapshot = create_snapshot(repo, project_id, repository_id, snapshot_root, SnapshotPolicy())
    generation = extract_generation(
        snapshot,
        snapshot_root / snapshot.snapshot_id / "source",
        tmp_path / "extraction",
        graphify_config(tmp_path),
    )
    nodes = {node.symbol_id: node for node in generation.nodes}
    edge = next(
        edge for edge in generation.edges
        if nodes[edge.source].name == source_name and nodes[edge.target].name == target_name and edge.kind == "calls"
    )
    store = PublicationStore(tmp_path / "publication")
    receipt = store.publish(store.stage(generation))
    request = {
        "contract": "knowitall.code-context/v1",
        "request_id": f"request-{fixture}",
        "project_id": project_id,
        "repository_id": repository_id,
        "selector": {
            "mode": "exact",
            "snapshot_id": snapshot.snapshot_id,
            "generation_id": generation.generation_id,
            "freshness": "require_current",
        },
        "query": {
            "kind": "dependencies",
            "symbol_id": edge.source,
            "direction": "outgoing",
            "relationship_kinds": ["calls"],
        },
    }

    response = QueryService(store).execute(request)

    validate_query_response(response, expected_request=request)
    assert response["status"] in {"ok", "partial"}
    assert response["resolved"] == {
        "snapshot_id": snapshot.snapshot_id,
        "commit": snapshot.commit,
        "content_manifest_digest": snapshot.content_manifest_digest,
        "generation_id": generation.generation_id,
        "artifact_digest": generation.artifact_digest,
    }
    match = next(item for item in response["evidence"] if item["evidence_id"] == edge.evidence_id)
    assert match["subject"] == {"symbol_id": edge.source, "name": source_name}
    assert match["object"] == {"symbol_id": edge.target, "name": target_name}
    assert match["locator"]["start"] == {"line": line, "column": 1}
    assert match["locator"]["end"] == {"line": line + 1, "column": 1}
    assert match["locator"]["content_digest"] == edge.content_digest
    assert receipt.generation.generation_id == response["resolved"]["generation_id"]
