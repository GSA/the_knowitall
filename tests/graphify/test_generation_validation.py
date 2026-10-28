import hashlib
import json
from dataclasses import replace

import pytest

from knowitall_graphify import GenerationValidationError, normalize_generation
from knowitall_graphify.normalize import native_graphify_payload
from knowitall_snapshot import SnapshotPolicy, create_snapshot


def valid_raw(snapshot):
    paths = [entry.path for entry in snapshot.included]
    first, second = paths[:2]
    return {
        "source_snapshot_id": snapshot.snapshot_id,
        "evidence_grade": "deterministic_extraction",
        "nodes": [
            {"id": "n1", "name": "submit_order", "path": first, "start": [1, 1], "end": [1, 2]},
            {"id": "n2", "name": "save_order", "path": second, "start": [1, 1], "end": [1, 2]},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2", "kind": "calls", "path": first, "start": [1, 1], "end": [1, 2]}],
        "processed_files": paths,
        "failed_files": [],
    }


@pytest.fixture
def snapshot(make_repo, tmp_path):
    repo = make_repo()
    return create_snapshot(repo, "project", "repo", tmp_path / "snapshots", SnapshotPolicy())


def normalize(snapshot, raw):
    data = json.dumps(raw, sort_keys=True).encode()
    return normalize_generation(snapshot, data, expected_digest="sha256:" + hashlib.sha256(data).hexdigest())


def test_rejects_malformed_graph_json(snapshot):
    with pytest.raises(GenerationValidationError, match="malformed graph JSON"):
        normalize_generation(snapshot, b"{")


def test_rejects_node_without_source_locator(snapshot):
    raw = valid_raw(snapshot)
    del raw["nodes"][0]["path"]
    with pytest.raises(GenerationValidationError, match="source locator"):
        normalize(snapshot, raw)


def test_rejects_dangling_edge_endpoint(snapshot):
    raw = valid_raw(snapshot)
    raw["edges"][0]["target"] = "missing"
    with pytest.raises(GenerationValidationError, match="dangling"):
        normalize(snapshot, raw)


def test_rejects_artifact_digest_mismatch(snapshot):
    raw = json.dumps(valid_raw(snapshot), sort_keys=True).encode()
    with pytest.raises(GenerationValidationError, match="artifact digest"):
        normalize_generation(snapshot, raw, expected_digest="sha256:" + "0" * 64)


def test_rejects_source_snapshot_mismatch(snapshot):
    raw = valid_raw(snapshot)
    raw["source_snapshot_id"] = "other"
    with pytest.raises(GenerationValidationError, match="source snapshot"):
        normalize(snapshot, raw)


def test_rejects_unaccounted_source_file(snapshot):
    raw = valid_raw(snapshot)
    raw["processed_files"].pop()
    with pytest.raises(GenerationValidationError, match="unaccounted"):
        normalize(snapshot, raw)


def test_incomplete_inventory_makes_generation_partial(snapshot):
    incomplete = replace(snapshot, inventory_complete=False, failed=({"path": ".", "reason": "listing_failed"},))
    generation = normalize(incomplete, valid_raw(incomplete))

    assert generation.state == "partial"
    assert generation.coverage.inventory == "partial"
    assert generation.coverage.relevant_scope == "partial"
    assert "listing_failed" in generation.coverage.limitations


def test_parser_failure_makes_generation_partial(snapshot):
    raw = valid_raw(snapshot)
    failed = raw["processed_files"].pop()
    raw["failed_files"] = [{"path": failed, "reason": "parser_error"}]
    generation = normalize(snapshot, raw)

    assert generation.state == "partial"
    assert generation.coverage.extraction == "partial"
    assert generation.failed_files == ((failed, "parser_error"),)


def test_rejects_model_or_generated_evidence_when_disabled(snapshot):
    raw = valid_raw(snapshot)
    raw["evidence_grade"] = "generated_narrative"
    with pytest.raises(GenerationValidationError, match="model-derived"):
        normalize(snapshot, raw)


def test_native_translation_marks_admitted_files_without_ast_evidence_partial(snapshot):
    raw = json.dumps({
        "nodes": [{"id": "n1", "label": "orders.py", "source_file": "src/orders.py", "source_location": "L1", "_origin": "ast"}],
        "edges": [],
    }).encode()

    translated = json.loads(native_graphify_payload(snapshot, raw))

    assert translated["processed_files"] == ["src/orders.py"]
    assert translated["failed_files"] == [{"path": "src/store.py", "reason": "unsupported_or_no_ast_evidence"}]


def test_native_line_locator_maps_to_whole_source_line(snapshot):
    raw = json.dumps({
        "nodes": [{"id": "n1", "label": "submit_order()", "source_file": "src/orders.py", "source_location": "L4", "_origin": "ast"}],
        "edges": [],
    }).encode()

    translated = json.loads(native_graphify_payload(snapshot, raw))

    assert translated["nodes"][0]["start"] == [4, 1]
    assert translated["nodes"][0]["end"] == [5, 1]


def test_normalized_generation_is_deterministic_and_source_bound(snapshot):
    raw = valid_raw(snapshot)
    first = normalize(snapshot, raw)
    second = normalize(snapshot, raw)

    assert first == second
    assert first.snapshot.snapshot_id == snapshot.snapshot_id
    assert first.generation_id.startswith("gen-")
    assert first.nodes[0].content_digest.startswith("sha256:")
