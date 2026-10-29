import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


PINNED_DISTRIBUTIONS = (
    ("graphifyy", "0.9.96"), ("networkx", "3.7"), ("numpy", "2.5.4"),
    ("PyYAML", "6.0.3"), ("RapidFuzz", "3.14.6"), ("tree-sitter", "0.25.2"),
    ("tree-sitter-bash", "0.25.1"), ("tree-sitter-c", "0.24.2"),
    ("tree-sitter-c-sharp", "0.23.5"), ("tree-sitter-cpp", "0.23.4"),
    ("tree-sitter-elixir", "0.3.5"), ("tree-sitter-fortran", "0.6.0"),
    ("tree-sitter-go", "0.25.0"), ("tree-sitter-groovy", "0.1.2"),
    ("tree-sitter-java", "0.23.5"), ("tree-sitter-javascript", "0.25.0"),
    ("tree-sitter-json", "0.24.8"), ("tree-sitter-julia", "0.23.1"),
    ("tree-sitter-kotlin", "1.1.0"), ("tree-sitter-lua", "0.5.0"),
    ("tree-sitter-objc", "3.0.2"), ("tree-sitter-php", "0.24.1"),
    ("tree-sitter-powershell", "0.26.4"), ("tree-sitter-python", "0.25.0"),
    ("tree-sitter-ruby", "0.23.1"), ("tree-sitter-rust", "0.24.2"),
    ("tree-sitter-scala", "0.26.3"), ("tree-sitter-swift", "0.7.4"),
    ("tree-sitter-typescript", "0.23.2"), ("tree-sitter-verilog", "1.0.3"),
    ("tree-sitter-zig", "1.1.2"),
)

_PROBE = r"""import importlib.util,json,platform,sys
from importlib.metadata import distribution
from pathlib import Path
root=Path(sys.argv[1]).resolve(); sys.path.insert(0,str(root))
versions={name:distribution(name).version for name in json.loads(%r)}
spec=importlib.util.find_spec('graphify')
if spec is None or spec.origin is None or not Path(spec.origin).resolve().is_relative_to(root):
 raise RuntimeError('graphify module does not resolve inside the configured runtime root')
print(json.dumps({'python':platform.python_version(),'distributions':versions,'graphify_origin':spec.origin},sort_keys=True))
""" % json.dumps([name for name, _ in PINNED_DISTRIBUTIONS])

_BOOTSTRAP = "import runpy,sys;root=sys.argv[1];args=sys.argv[2:];sys.path.insert(0,root);sys.argv=['graphify',*args];runpy.run_module('graphify',run_name='__main__',alter_sys=False)"


@dataclass(frozen=True)
class GraphifyConfig:
    executable: Path
    timeout_seconds: float = 120.0
    receipt_limit: int = 16_384
    allowed_source_root: Path | None = None
    allowed_output_root: Path | None = None
    python_path: str | None = None
    expected_executable_digest: str | None = None


@dataclass(frozen=True)
class ExecutionReceipt:
    returncode: int
    stdout: str
    stderr: str
    argv: tuple[str, ...]
    engine_identity: str
    runtime_identity: str
    executable_digest: str


class GraphifyExecutionError(RuntimeError):
    def __init__(self, message: str, *, returncode: int | None, stdout: str = "", stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def executable_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.resolve(strict=True).read_bytes()).hexdigest()


def _confined(path: Path, root: Path | None, label: str) -> Path:
    resolved = path.resolve()
    if root is not None and not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"{label} path is outside allowed root")
    return resolved


def _bounded(value: str | bytes, limit: int) -> str:
    data = value if isinstance(value, bytes) else value.encode("utf-8", "replace")
    return data[:limit].decode("utf-8", "ignore")


def _environment() -> dict[str, str]:
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": os.devnull, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _probe(argv: list[str], config: GraphifyConfig, env: dict[str, str]):
    try:
        return subprocess.run(argv, cwd="/", env=env, text=True, capture_output=True, timeout=config.timeout_seconds, check=False)
    except subprocess.TimeoutExpired as error:
        raise GraphifyExecutionError("runtime identity probe timed out", returncode=None, stdout=_bounded(error.stdout or "", config.receipt_limit), stderr=_bounded(error.stderr or "", config.receipt_limit)) from error


def _runtime_receipt(config: GraphifyConfig, interpreter: Path, runtime_root: Path, env: dict[str, str]) -> tuple[str, str, str]:
    digest = executable_digest(interpreter)
    result = _probe([str(interpreter), "-I", "-S", "-c", _PROBE, str(runtime_root)], config, env)
    if result.returncode:
        raise GraphifyExecutionError("runtime identity mismatch", returncode=result.returncode, stdout=_bounded(result.stdout, config.receipt_limit), stderr=_bounded(result.stderr, config.receipt_limit))
    try:
        value = json.loads(result.stdout)
        actual = value["distributions"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise GraphifyExecutionError("runtime identity probe malformed", returncode=result.returncode) from error
    if actual != dict(PINNED_DISTRIBUTIONS):
        raise GraphifyExecutionError("runtime identity mismatch", returncode=result.returncode, stdout=_bounded(result.stdout, config.receipt_limit))
    engine = f"graphifyy:{actual['graphifyy']}"
    packages = ";".join(f"{name}:{actual[name]}" for name in sorted(actual, key=str.casefold) if name != "graphifyy")
    return engine, f"python:{value['python']};{packages}", digest


def run_graphify(source_dir: Path, output_dir: Path, config: GraphifyConfig) -> ExecutionReceipt:
    interpreter = config.executable.resolve(strict=True)
    if not interpreter.is_file():
        raise ValueError("configured Python interpreter must be a file")
    if config.expected_executable_digest != executable_digest(interpreter):
        raise GraphifyExecutionError("Python interpreter digest mismatch", returncode=None)
    source = _confined(source_dir, config.allowed_source_root, "source")
    if not source.is_dir():
        raise ValueError("source path must be a directory")
    output = _confined(output_dir, config.allowed_output_root, "output")
    output.parent.mkdir(parents=True, exist_ok=True)
    if config.python_path is None or os.pathsep in config.python_path:
        raise ValueError("python_path must name one trusted runtime root")
    runtime_root = Path(config.python_path).resolve(strict=True)
    env = _environment()
    engine_identity, runtime_identity, digest = _runtime_receipt(config, interpreter, runtime_root, env)
    argv = (str(interpreter), "-I", "-S", "-c", _BOOTSTRAP, str(runtime_root), "extract", str(source), "--out", str(output), "--code-only", "--no-cluster")
    env["PYTHONPATH"] = str(runtime_root)
    try:
        result = subprocess.run(argv, shell=False, cwd="/", env=env, text=True, capture_output=True, timeout=config.timeout_seconds, check=False)
    except subprocess.TimeoutExpired as error:
        raise GraphifyExecutionError("Graphify extraction timed out", returncode=None, stdout=_bounded(error.stdout or "", config.receipt_limit), stderr=_bounded(error.stderr or "", config.receipt_limit)) from error
    stdout = _bounded(result.stdout, config.receipt_limit)
    stderr = _bounded(result.stderr, config.receipt_limit)
    if result.returncode:
        raise GraphifyExecutionError("Graphify extraction failed", returncode=result.returncode, stdout=stdout, stderr=stderr)
    return ExecutionReceipt(result.returncode, stdout, stderr, argv, engine_identity, runtime_identity, digest)
