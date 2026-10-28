import json
import os
import stat
import sys
from pathlib import Path

import pytest

from knowitall_graphify import GraphifyConfig, GraphifyExecutionError, run_graphify


def executable_fake(tmp_path: Path) -> Path:
    source = Path(__file__).with_name("fake_graphify.py")
    fake = tmp_path / "graphify"
    fake.write_bytes(source.read_bytes())
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return fake


def test_adapter_uses_confined_paths_code_only_flags_and_allowlisted_environment(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "staging" / "output"
    executable = executable_fake(tmp_path)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "must-not-leak")

    receipt = run_graphify(source, output, GraphifyConfig(executable=executable, timeout_seconds=5))

    invocation = json.loads((output / "invocation.json").read_text())
    assert invocation["argv"] == ["extract", str(source.resolve()), "--out", str(output.resolve()), "--code-only", "--no-cluster"]
    assert not ({"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"} & invocation["env"].keys())
    assert receipt.returncode == 0
    assert receipt.stdout == "fake stdout\n"
    assert receipt.stderr == "fake stderr\n"


@pytest.mark.parametrize("which", ["source", "output"])
def test_adapter_rejects_paths_outside_configured_roots(tmp_path, which):
    root = tmp_path / "root"
    source = root / "source"
    output = root / "output"
    source.mkdir(parents=True)
    executable = executable_fake(tmp_path)
    config = GraphifyConfig(executable=executable, allowed_source_root=root, allowed_output_root=root)
    if which == "source":
        source = tmp_path / "elsewhere"
        source.mkdir()
    else:
        output = tmp_path / "elsewhere"

    with pytest.raises(ValueError, match="outside allowed"):
        run_graphify(source, output, config)


def test_adapter_captures_timeout_and_never_uses_shell(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    executable = tmp_path / "graphify"
    executable.write_text("#!/bin/sh\nsleep 5\n")
    executable.chmod(0o755)

    with pytest.raises(GraphifyExecutionError, match="timed out") as caught:
        run_graphify(source, tmp_path / "output", GraphifyConfig(executable=executable, timeout_seconds=0.01))

    assert caught.value.returncode is None


def test_adapter_bounds_receipt_and_treats_nonzero_as_error(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    executable = tmp_path / "graphify"
    executable.write_text("#!/bin/sh\nprintf '%0200d' 0\nprintf '%0200d' 0 >&2\nexit 7\n")
    executable.chmod(0o755)

    with pytest.raises(GraphifyExecutionError) as caught:
        run_graphify(source, tmp_path / "output", GraphifyConfig(executable=executable, receipt_limit=32))

    assert caught.value.returncode == 7
    assert len(caught.value.stdout.encode()) <= 32
    assert len(caught.value.stderr.encode()) <= 32
