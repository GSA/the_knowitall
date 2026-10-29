import os
from dataclasses import replace
from pathlib import Path

import pytest

from knowitall_graphify import GraphifyConfig, executable_digest
from knowitall_publication import PublicationStore
from knowitall_query import QueryService
from knowitall_snapshot import SnapshotPolicy, create_snapshot
from knowitall_updates import UpdateLedger, UpdateRunner

RUNTIME = os.environ.get("KNOWITALL_GRAPHIFY_RUNTIME")
pytestmark = pytest.mark.skipif(not RUNTIME, reason="pinned runtime required")


def test_real_update_exclusions_and_unsupported_sources_are_honest(make_repo, tmp_path):
    repo = make_repo()
    interpreter = Path(RUNTIME) / "bin/python"
    config = GraphifyConfig(interpreter, python_path=str(Path(RUNTIME) / "lib/python3.14/site-packages"), expected_executable_digest=executable_digest(interpreter))
    store = PublicationStore(tmp_path / "store")
    runner = UpdateRunner(UpdateLedger(tmp_path / "updates", store), config)
    snapshot = create_snapshot(repo, "p", "r", tmp_path / "snapshots", SnapshotPolicy())
    runner.submit("initial", snapshot, expected_current=None)
    initial = runner.resume("initial").receipt.generation
    # Exclude all code; inventory remains complete, but extraction is explicitly partial.
    import hashlib
    excluded = replace(snapshot, snapshot_id="snap-excluded", included=(), content_manifest_digest="sha256:" + hashlib.sha256(b"").hexdigest(), excluded=tuple({"path": entry.path, "reason": "policy_excluded"} for entry in snapshot.included))
    runner.submit("excluded", excluded, expected_current=initial)
    selected = runner.resume("excluded").receipt.generation
    generation = store.open_generation(selected)
    assert generation.nodes == ()
    assert generation.coverage.extraction == "partial"
    request = {"contract": "knowitall.code-context/v1", "request_id": "q", "project_id": "p", "repository_id": "r", "selector": {"mode": "current"}, "query": {"kind": "symbol", "name": "absent", "match": "exact"}}
    response = QueryService(store).execute(request)
    assert response["status"] == "partial"
    assert {item["reason"] for item in response["missing_evidence"]} == {"policy_excluded"}
    assert response["resolved"]["commit"] == snapshot.commit
