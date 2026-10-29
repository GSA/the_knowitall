import os
import subprocess
from pathlib import Path


class GitError(ValueError):
    pass


def run_git(repo: Path, *args: str, text: bool = True):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.autocrlf=false", "-c", "core.fsmonitor=false", *args],
        cwd=repo, env=env, capture_output=True, text=text, check=False,
    )
    if result.returncode:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise GitError(f"git {args[0]} failed: {stderr.strip()}")
    return result.stdout


def commit_identity(repo: Path) -> str:
    object_format = run_git(repo, "rev-parse", "--show-object-format").strip()
    commit = run_git(repo, "rev-parse", "--verify", "HEAD^{commit}").strip()
    return f"{object_format}:{commit}"


def status_entries(repo: Path) -> bytes:
    return run_git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", text=False)
