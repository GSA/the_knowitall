import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .git import GitError


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
        "HOME": os.environ.get("HOME", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise GitError(f"git {args[0]} failed: {result.stderr.strip()}")


def acquire_remote(origin: str, destination: Path) -> AcquiredRepository:
    """Clone or fast-forward one explicitly configured remote without credentials."""
    normalized = _safe_origin(origin)
    destination = destination.resolve()
    if destination.exists():
        if not (destination / ".git").exists():
            raise ValueError("remote destination exists but is not a Git checkout")
        _run("remote", "set-url", "origin", normalized, cwd=destination)
        _run("fetch", "--prune", "--no-tags", "origin", cwd=destination)
        _run("reset", "--hard", "origin/HEAD", cwd=destination)
        _run("clean", "-ffd", cwd=destination)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run("clone", "--no-tags", "--no-recurse-submodules", normalized, str(destination))
    return AcquiredRepository(destination, normalized)
