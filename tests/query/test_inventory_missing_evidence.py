import json
from dataclasses import replace

from knowitall_graphify import normalize_generation
from knowitall_publication import PublicationStore
from knowitall_query import QueryService


def publish_snapshot(snapshot, raw, tmp_path):
    generation = normalize_generation(snapshot, json.dumps(raw, sort_keys=True).encode())
    store = PublicationStore(tmp_path / "store")
    store.publish(store.stage(generation))
    return store


def test_inventory_failure_is_machine_readable_missing_evidence(generation_factory, request_factory, tmp_path):
    _, snapshot = generation_factory()
    incomplete = replace(snapshot, inventory_complete=False, failed=({"path": ".", "reason": "inventory_listing_failed"},))
    raw = json.dumps({
        "source_snapshot_id": incomplete.snapshot_id,
        "evidence_grade": "deterministic_extraction",
        "processed_files": [entry.path for entry in incomplete.included],
        "failed_files": [],
        "nodes": [],
        "edges": [],
    }, sort_keys=True).encode()
    generation = normalize_generation(incomplete, raw)
    store = PublicationStore(tmp_path / "store")
    store.publish(store.stage(generation))

    response = QueryService(store).execute(request_factory(symbol="missing"))

    assert response["status"] == "partial"
    assert response["missing_evidence"] == [
        {"kind": "inventory", "scope": ".", "reason": "inventory_listing_failed"}
    ]


def test_excluded_path_and_symbol_absence_are_not_authoritative(generation_factory, request_factory, tmp_path):
    _, snapshot = generation_factory()
    excluded = replace(snapshot, excluded=({"path": "vendor/client", "reason": "submodule_excluded"},))
    raw = {
        "source_snapshot_id": excluded.snapshot_id,
        "evidence_grade": "deterministic_extraction",
        "processed_files": [entry.path for entry in excluded.included],
        "failed_files": [],
        "nodes": [],
        "edges": [],
    }
    store = publish_snapshot(excluded, raw, tmp_path)
    service = QueryService(store)

    path_response = service.execute(request_factory(query={"kind": "path", "path": "vendor/client"}))
    symbol_response = service.execute(request_factory(query={"kind": "symbol", "name": "unknown", "match": "exact"}))
    dependency_response = service.execute(request_factory())

    expected = {"kind": "exclusion", "scope": "vendor/client", "reason": "submodule_excluded"}
    assert path_response["status"] == "partial"
    assert expected in path_response["missing_evidence"]
    assert symbol_response["status"] == "partial"
    assert expected in symbol_response["missing_evidence"]
    assert dependency_response["status"] == "partial"
    assert expected in dependency_response["missing_evidence"]
