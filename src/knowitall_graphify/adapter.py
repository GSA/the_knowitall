import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GraphifyConfig:
    executable: Path
    timeout_seconds: float = 120.0
    receipt_limit: int = 16_384
    allowed_source_root: Path | None = None
    allowed_output_root: Path | None = None
    python_path: str | None = None


@dataclass(frozen=True)
class ExecutionReceipt:
    returncode: int
    stdout: str
    stderr: str
    argv: tuple[str, ...]


class GraphifyExecutionError(RuntimeError):
    def __init__(self, message: str, *, returncode: int | None, stdout: str = "", stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _confined(path: Path, root: Path | None, label: str) -> Path:
    resolved = path.resolve()
    if root is not None and not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"{label} path is outside allowed root")
    return resolved


def _bounded(value: str, limit: int) -> str:
    data = value.encode("utf-8", "replace")[:limit]
    return data.decode("utf-8", "ignore")


def run_graphify(source_dir: Path, output_dir: Path, config: GraphifyConfig) -> ExecutionReceipt:
    executable = config.executable.resolve(strict=True)
    source = _confined(source_dir, config.allowed_source_root, "source")
    if not source.is_dir():
        raise ValueError("source path must be a directory")
    output = _confined(output_dir, config.allowed_output_root, "output")
    output.parent.mkdir(parents=True, exist_ok=True)
    argv = (
        str(executable), "extract", str(source), "--out", str(output),
        "--code-only", "--no-cluster",
    )
    env = {"PATH": os.pathsep.join((str(executable.parent), "/usr/local/bin", "/usr/bin", "/bin")), "HOME": os.devnull, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
    if config.python_path is not None:
        env["PYTHONPATH"] = config.python_path
    try:
        result = subprocess.run(argv, shell=False, env=env, text=True, capture_output=True, timeout=config.timeout_seconds, check=False)
    except subprocess.TimeoutExpired as error:
        raise GraphifyExecutionError("Graphify extraction timed out", returncode=None, stdout=_bounded(error.stdout or "", config.receipt_limit), stderr=_bounded(error.stderr or "", config.receipt_limit)) from error
    stdout = _bounded(result.stdout, config.receipt_limit)
    stderr = _bounded(result.stderr, config.receipt_limit)
    if result.returncode:
        raise GraphifyExecutionError("Graphify extraction failed", returncode=result.returncode, stdout=stdout, stderr=stderr)
    return ExecutionReceipt(result.returncode, stdout, stderr, argv)
