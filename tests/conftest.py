import json
import shutil
import subprocess
from pathlib import Path

import pytest

from knowitall_graphify import normalize_generation
from knowitall_publication import PublicationStore
from knowitall_snapshot import SnapshotPolicy, create_snapshot


FIXTURES = Path(__file__).parent / "fixtures" / "repos"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo,
        text=True,
        check=True,
        capture_output=True,
    )
    return result.stdout.strip()


@pytest.fixture
def make_repo(tmp_path):
    counter = 0

    def make(fixture: str = "python_service") -> Path:
        nonlocal counter
        counter += 1
        repo = tmp_path / f"repo-{counter}"
        shutil.copytree(FIXTURES / fixture, repo, ignore=shutil.ignore_patterns("__pycache__"))
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Synthetic Test")
        git(repo, "config", "user.email", "synthetic@example.invalid")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "fixture")
        return repo

    return make


@pytest.fixture
def generation_factory(make_repo, tmp_path):
    counter = 0

    def make(*, project="project-a", repository="repo-a", fixture="python_service"):
        nonlocal counter
        counter += 1
        repo = make_repo(fixture)
        snapshot = create_snapshot(repo, project, repository, tmp_path / f"snapshots-{counter}", SnapshotPolicy())
        paths = [entry.path for entry in snapshot.included]
        raw = json.dumps({
            "source_snapshot_id": snapshot.snapshot_id,
            "evidence_grade": "deterministic_extraction",
            "processed_files": paths,
            "failed_files": [],
            "nodes": [
                {"id": "source", "name": "source", "path": paths[0], "start": [1, 1], "end": [2, 1]},
                {"id": "target", "name": "target", "path": paths[-1], "start": [1, 1], "end": [2, 1]},
            ],
            "edges": [{"id": "edge", "source": "source", "target": "target", "kind": "calls", "path": paths[0], "start": [1, 1], "end": [2, 1]}],
        }, sort_keys=True).encode()
        return normalize_generation(snapshot, raw), snapshot

    return make


@pytest.fixture
def published_graph(make_repo, tmp_path):
    def make(*, project="project-a", repository="repo-a", partial=False, duplicate_names=False, edge_count=1):
        repo = make_repo()
        snapshot = create_snapshot(repo, project, repository, tmp_path / f"query-snapshots-{project}-{repository}", SnapshotPolicy())
        paths = [entry.path for entry in snapshot.included]
        nodes = [
            {"id": "orders.submit", "name": "submit", "path": paths[0], "start": [4, 1], "end": [6, 1]},
            {"id": "store.save", "name": "save", "path": paths[1], "start": [1, 1], "end": [3, 1]},
        ]
        if duplicate_names:
            nodes.append({"id": "other.submit", "name": "submit", "path": paths[0], "start": [7, 1], "end": [8, 1]})
        processed, failed = list(paths), []
        if partial:
            failed_path = processed.pop()
            failed = [{"path": failed_path, "reason": "parser_error"}]
            nodes = [node for node in nodes if node["path"] != failed_path]
        raw = json.dumps({
            "source_snapshot_id": snapshot.snapshot_id,
            "evidence_grade": "deterministic_extraction",
            "processed_files": processed,
            "failed_files": failed,
            "nodes": nodes,
            "edges": [{"id": f"calls-save-{index}", "source": "orders.submit", "target": "store.save", "kind": "calls", "path": paths[0], "start": [5, 1], "end": [6, 1]} for index in range(edge_count)] if not partial else [],
        }, sort_keys=True).encode()
        generation = normalize_generation(snapshot, raw)
        store = PublicationStore(tmp_path / "query-store")
        store.publish(store.stage(generation))
        return store, generation
    return make


@pytest.fixture
def request_factory():
    def make(*, request_id="request-1", project="project-a", repository="repo-a", selector=None, symbol="orders.submit", direction="outgoing", kinds=None, continuation=None, query=None):
        request = {
            "contract": "knowitall.code-context/v1",
            "request_id": request_id,
            "project_id": project,
            "repository_id": repository,
            "selector": selector or {"mode": "current"},
            "query": query or {"kind": "dependencies", "symbol_id": symbol, "direction": direction, "relationship_kinds": kinds or ["calls"]},
        }
        if continuation is not None:
            request["continuation"] = continuation
        return request
    return make
