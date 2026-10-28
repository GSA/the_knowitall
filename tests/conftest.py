import shutil
import subprocess
from pathlib import Path

import pytest


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
