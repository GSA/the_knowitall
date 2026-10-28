import json
import shutil
import subprocess
from pathlib import Path

import pytest

from knowitall_graphify import normalize_generation
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
        shutil.copytree(FIXTURES / fixture, repo)
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
