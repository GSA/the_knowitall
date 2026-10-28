import hashlib
import os
from pathlib import Path

import pytest

from knowitall_graphify import GraphifyConfig, extract_generation
from knowitall_snapshot import SnapshotPolicy, create_snapshot


RUNTIME = os.environ.get("KNOWITALL_GRAPHIFY_RUNTIME")
pytestmark = pytest.mark.skipif(not RUNTIME, reason="verified pinned Graphify runtime not installed")


def config(tmp_path: Path) -> GraphifyConfig:
    wrapper = tmp_path / "graphify"
    wrapper.write_text(f"#!/bin/sh\nexec python3 -m graphify \"$@\"\n")
    wrapper.chmod(0o755)
    return GraphifyConfig(executable=wrapper, python_path=RUNTIME)


@pytest.mark.parametrize(
    ("fixture", "relationship", "source_line"),
    [
        ("python_service", ("submit_order()", "save_order()", "calls"), 5),
        ("typescript_client", ("loadOrder()", "fetchOrder()", "calls"), 4),
    ],
)
def test_real_pinned_extraction_is_offline_source_bound_and_deterministic(make_repo, tmp_path, fixture, relationship, source_line):
    repo = make_repo(fixture)
    snapshots = tmp_path / "snapshots"
    snapshot = create_snapshot(repo, "project-acme", f"repo-{fixture}", snapshots, SnapshotPolicy())
    source = snapshots / snapshot.snapshot_id / "source"
    first = extract_generation(snapshot, source, tmp_path / "first", config(tmp_path))
    second = extract_generation(snapshot, source, tmp_path / "second", config(tmp_path))

    nodes = {node.symbol_id: node for node in first.nodes}
    matches = [edge for edge in first.edges if (nodes[edge.source].name, nodes[edge.target].name, edge.kind) == relationship]
    assert len(matches) == 1
    assert matches[0].source_range.start_line == source_line
    assert matches[0].source_range.end_line == source_line + 1
    assert matches[0].source_range.start_column == matches[0].source_range.end_column == 1
    assert matches[0].content_digest.startswith("sha256:")
    assert first.nodes == second.nodes
    assert first.edges == second.edges
    assert first.raw_artifact == second.raw_artifact
    assert first.artifact_digest == second.artifact_digest
    assert first.generation_id == second.generation_id
    assert first.engine_identity == "graphifyy:0.9.96"
    assert "tree-sitter:0.25.2" in first.runtime_identity
    assert first.config_identity.startswith("sha256:")
    assert first.model_routes_enabled is False
    identity = "\0".join((snapshot.snapshot_id, first.artifact_digest, first.engine_identity, first.runtime_identity, first.config_identity))
    assert first.generation_id == "gen-" + hashlib.sha256(identity.encode()).hexdigest()
