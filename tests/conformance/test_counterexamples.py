import json
import subprocess

import pytest

from knowitall_graphify import normalize_generation
from knowitall_publication import PublicationInterrupted, PublicationStore
from knowitall_query import QueryService
from knowitall_snapshot import SnapshotPolicy, create_snapshot


def _git(repo, *args):
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=repo, check=True, capture_output=True)


def _empty_generation(snapshot):
    raw = json.dumps({
        "source_snapshot_id": snapshot.snapshot_id,
        "evidence_grade": "deterministic_extraction",
        "processed_files": [entry.path for entry in snapshot.included],
        "failed_files": [],
        "nodes": [],
        "edges": [],
    }, sort_keys=True).encode()
    return normalize_generation(snapshot, raw)


def test_wrong_repository_and_duplicate_names_never_cross_identity(published_graph, request_factory):
    store, _ = published_graph(duplicate_names=True)

    wrong = QueryService(store).execute(request_factory(repository="repo-other"))
    exact_duplicate = QueryService(store).execute(request_factory(symbol="other.submit"))

    assert wrong["status"] == "unavailable"
    assert wrong["resolved"] is None
    assert exact_duplicate["status"] == "ok"
    assert exact_duplicate["evidence"] == []
    assert exact_duplicate["ambiguities"] == []


def test_missing_symbol_is_not_found_only_when_coverage_is_complete(published_graph, request_factory):
    complete_store, _ = published_graph(repository="complete")
    partial_store, _ = published_graph(repository="partial", partial=True)

    complete = QueryService(complete_store).execute(request_factory(repository="complete", symbol="missing"))
    partial = QueryService(partial_store).execute(request_factory(repository="partial", symbol="missing"))

    assert complete["status"] == "not_found"
    assert partial["status"] == "partial"
    assert partial["missing_evidence"]


def test_interrupted_publication_is_unavailable_until_successful_retry(generation_factory, tmp_path, request_factory):
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path / "interrupted-store")
    staged = store.stage(generation)

    with pytest.raises(PublicationInterrupted):
        store.publish(staged, failpoint="before_current_replace")
    assert QueryService(store).execute(request_factory(symbol="source"))["status"] == "unavailable"

    store.publish(staged)
    assert QueryService(store).execute(request_factory(symbol="source"))["status"] == "ok"


def test_dirty_default_rejection_has_no_snapshot(make_repo, tmp_path):
    repo = make_repo()
    (repo / "src" / "orders.py").write_text("dirty = True\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dirty Git input rejected"):
        create_snapshot(repo, "project-a", "repo-a", tmp_path / "snapshots", SnapshotPolicy())


def test_changed_and_deleted_revision_cannot_return_old_evidence_as_current(make_repo, tmp_path, request_factory):
    repo = make_repo()
    snapshot_root = tmp_path / "revision-snapshots"
    first_snapshot = create_snapshot(repo, "project-a", "repo-a", snapshot_root, SnapshotPolicy())
    first_generation = _empty_generation(first_snapshot)
    store = PublicationStore(tmp_path / "revision-store")
    store.publish(store.stage(first_generation))

    (repo / "src" / "orders.py").write_text("def replacement():\n    return None\n", encoding="utf-8")
    (repo / "src" / "store.py").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "change and delete")
    second_snapshot = create_snapshot(repo, "project-a", "repo-a", snapshot_root, SnapshotPolicy())
    second_generation = _empty_generation(second_snapshot)
    store.publish(store.stage(second_generation))

    old_selector = {
        "mode": "exact",
        "snapshot_id": first_snapshot.snapshot_id,
        "generation_id": first_generation.generation_id,
        "freshness": "require_current",
    }
    stale = QueryService(store).execute(request_factory(selector=old_selector, symbol="missing"))
    current = QueryService(store).execute(request_factory(symbol="missing"))

    assert stale["status"] == "stale"
    assert stale["resolved"]["generation_id"] == first_generation.generation_id
    assert current["status"] == "not_found"
    assert current["resolved"]["generation_id"] == second_generation.generation_id
    assert current["evidence"] == []


def test_pagination_never_silently_discards_evidence(published_graph, request_factory):
    store, _ = published_graph(edge_count=3)
    service = QueryService(store, page_size=2, continuation_secret=b"synthetic-conformance-secret")

    first = service.execute(request_factory())
    second = service.execute(request_factory(continuation=first["continuation"]))

    assert first["truncated"] is True and first["continuation"]
    assert second["truncated"] is False and second["continuation"] is None
    assert [item["evidence_id"] for item in first["evidence"] + second["evidence"]] == [
        "calls-save-0", "calls-save-1", "calls-save-2"
    ]
