import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .git import GitError, run_git


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


def _reset_local_config(destination: Path, origin: str, object_format: str) -> None:
    (destination / ".git" / "config").unlink(missing_ok=True)
    _run("config", "--local", "core.repositoryformatversion", "1" if object_format != "sha1" else "0", cwd=destination)
    if object_format != "sha1":
        _run("config", "--local", "extensions.objectFormat", object_format, cwd=destination)
    _run("config", "--local", "core.filemode", "true", cwd=destination)
    _run("config", "--local", "core.bare", "false", cwd=destination)
    _run("remote", "add", "origin", origin, cwd=destination)


def acquire_remote(origin: str, destination: Path) -> AcquiredRepository:
    """Clone or refresh one explicitly configured remote without credential helpers or hooks."""
    normalized = _safe_origin(origin)
    destination = destination.resolve()
    if destination.exists():
        if not (destination / ".git").is_dir():
            raise ValueError("remote destination exists but is not a Git checkout")
        object_format = run_git(destination, "rev-parse", "--show-object-format").strip()
        _reset_local_config(destination, normalized, object_format)
        _run("fetch", "--prune", "--no-tags", "origin", "+HEAD:refs/remotes/origin/HEAD", cwd=destination)
        _run("reset", "--hard", "refs/remotes/origin/HEAD", cwd=destination)
        _run("clean", "-ffd", cwd=destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run("clone", "--no-tags", "--no-recurse-submodules", normalized, str(destination))
    return AcquiredRepository(destination, normalized)
