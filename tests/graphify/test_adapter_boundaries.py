import subprocess
import sys
from pathlib import Path

import pytest

import knowitall_graphify.adapter as adapter
from knowitall_graphify import GraphifyConfig, GraphifyExecutionError, executable_digest, run_graphify


def config(interpreter: Path, runtime_root: Path | None = None, **options) -> GraphifyConfig:
    interpreter = interpreter.resolve(strict=True)
    return GraphifyConfig(
        executable=interpreter,
        python_path=str(runtime_root) if runtime_root else None,
        expected_executable_digest=executable_digest(interpreter),
        **options,
    )


def test_bootstrap_uses_fixed_code_arguments_and_never_runs_startup_hook(tmp_path):
    marker = tmp_path / "startup-hook-ran"
    module = tmp_path / "graphify.py"
    module.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "assert sys.argv[1:] == ['extract', 'source', '--out', 'output', '--code-only', '--no-cluster']\n"
        f"Path({str(tmp_path / 'ran')!r}).touch()\n"
    )
    (tmp_path / "sitecustomize.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")

    argv = [sys.executable, "-I", "-S", "-c", adapter._BOOTSTRAP, str(tmp_path), "extract", "source", "--out", "output", "--code-only", "--no-cluster"]
    result = subprocess.run(argv, shell=False, cwd="/", env=adapter._environment(), capture_output=True, text=True)

    assert result.returncode == 0
    assert (tmp_path / "ran").exists()
    assert not marker.exists()


def test_environment_excludes_credentials_proxies_and_user_configuration():
    env = adapter._environment()

    assert set(env) == {"PATH", "HOME", "LANG", "LC_ALL"}
    assert env["HOME"] == "/dev/null"


@pytest.mark.parametrize("which", ["source", "output"])
def test_adapter_rejects_paths_outside_configured_roots(tmp_path, which):
    root = tmp_path / "root"
    source = root / "source"
    output = root / "output"
    source.mkdir(parents=True)
    value = config(Path(sys.executable), tmp_path, allowed_source_root=root, allowed_output_root=root)
    if which == "source":
        source = tmp_path / "elsewhere"
        source.mkdir()
    else:
        output = tmp_path / "elsewhere"

    with pytest.raises(ValueError, match="outside allowed"):
        run_graphify(source, output, value)


def test_adapter_requires_one_trusted_runtime_root(tmp_path):
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(ValueError, match="one trusted runtime root"):
        run_graphify(source, tmp_path / "output", config(Path(sys.executable)))


def test_adapter_never_executes_interpreter_before_digest_approval(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    marker = tmp_path / "executed"
    interpreter = tmp_path / "python"
    interpreter.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    interpreter.chmod(0o755)

    with pytest.raises(GraphifyExecutionError, match="interpreter digest mismatch"):
        run_graphify(source, tmp_path / "output", GraphifyConfig(
            executable=interpreter,
            python_path=str(tmp_path),
            expected_executable_digest="sha256:" + "0" * 64,
        ))

    assert not marker.exists()


def test_adapter_rejects_runtime_without_the_pinned_distributions(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (tmp_path / "graphify.py").write_text("raise RuntimeError('unverified engine ran')\n")

    with pytest.raises(GraphifyExecutionError, match="runtime identity mismatch"):
        run_graphify(source, tmp_path / "output", config(Path(sys.executable), tmp_path))


def test_probe_captures_timeout_and_bounds_receipts(tmp_path):
    value = config(Path(sys.executable), tmp_path, timeout_seconds=0.01, receipt_limit=32)

    with pytest.raises(GraphifyExecutionError, match="timed out") as caught:
        adapter._probe([sys.executable, "-c", "import time;time.sleep(5)"], value, adapter._environment())
    assert caught.value.returncode is None

    assert len(adapter._bounded("x" * 200, value.receipt_limit).encode()) <= 32
