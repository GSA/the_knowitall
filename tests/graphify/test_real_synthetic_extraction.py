import os
from pathlib import Path

import pytest

from knowitall_graphify import GraphifyConfig, GraphifyExecutionError, executable_digest, expected_generation_id, extract_generation, run_graphify
from knowitall_snapshot import SnapshotPolicy, create_snapshot


RUNTIME = os.environ.get("KNOWITALL_GRAPHIFY_RUNTIME")
pytestmark = pytest.mark.skipif(not RUNTIME, reason="verified pinned Graphify runtime not installed")


def config(tmp_path: Path) -> GraphifyConfig:
    interpreter = Path(RUNTIME) / "bin" / "python"
    package_root = Path(RUNTIME) / "lib" / "python3.14" / "site-packages"
    return GraphifyConfig(executable=interpreter, python_path=str(package_root), expected_executable_digest=executable_digest(interpreter))


def test_pinned_runtime_rejects_an_unapproved_interpreter(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    value = config(tmp_path)
    altered = GraphifyConfig(**{**value.__dict__, "expected_executable_digest": "sha256:" + "0" * 64})

    with pytest.raises(GraphifyExecutionError, match="interpreter digest mismatch"):
        run_graphify(source, tmp_path / "output", altered)


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
    assert first.runtime_identity.startswith("python:3.14")
    assert "tree-sitter:0.25.2" in first.runtime_identity
    assert "tree-sitter-python:0.25.0" in first.runtime_identity
    assert "tree-sitter-typescript:0.23.2" in first.runtime_identity
    assert first.config_identity.startswith("sha256:")
    assert first.model_routes_enabled is False
    assert first.generation_id == expected_generation_id(first)
