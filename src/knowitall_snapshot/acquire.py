import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .git import GitError, run_git
from .inventory import clean_inventory


@dataclass(frozen=True)
class AcquiredRepository:
    path: Path
    origin: str


def _safe_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credentials in remote origins are not allowed")
    if parsed.scheme in {"", "file"}:
        raw_path = parsed.path if parsed.scheme else origin
        return str(Path(raw_path).expanduser().resolve())
    if parsed.scheme not in {"https", "ssh"}:
        raise ValueError(f"unsupported remote origin scheme: {parsed.scheme!r}")
    return origin


def _run(*args: str, cwd: Path | None = None) -> None:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=", "-c", "core.fsmonitor=false", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise GitError(f"git {args[0]} failed: {result.stderr.strip()}")


def _reset_local_config(destination: Path, origin: str) -> None:
    (destination / ".git" / "config").unlink(missing_ok=True)
    _run("config", "--local", "core.repositoryformatversion", "0", cwd=destination)
    _run("config", "--local", "core.filemode", "true", cwd=destination)
    _run("config", "--local", "core.bare", "false", cwd=destination)
    _run("remote", "add", "origin", origin, cwd=destination)


def _materialize_commit(destination: Path, commit: str) -> None:
    entries, _excluded = clean_inventory(destination, commit)
    for child in destination.iterdir():
        if child.name != ".git":
            shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    for entry in entries:
        target = destination / entry.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(entry.data)
        target.chmod(stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if entry.mode == "100755" else 0))
    _run("read-tree", commit, cwd=destination)


def acquire_remote(origin: str, destination: Path) -> AcquiredRepository:
    """Fetch one explicitly configured remote and materialize committed blobs without checkout filters."""
    normalized = _safe_origin(origin)
    destination = destination.resolve()
    if destination.exists():
        if not (destination / ".git").is_dir():
            raise ValueError("remote destination exists but is not a Git checkout")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.mkdir()
        _run("init", "-q", cwd=destination)
    _reset_local_config(destination, normalized)
    _run("fetch", "--prune", "--no-tags", "origin", "+HEAD:refs/remotes/origin/HEAD", cwd=destination)
    commit = run_git(destination, "rev-parse", "--verify", "refs/remotes/origin/HEAD^{commit}").strip()
    _materialize_commit(destination, commit)
    _run("update-ref", "HEAD", commit, cwd=destination)
    return AcquiredRepository(destination, normalized)
