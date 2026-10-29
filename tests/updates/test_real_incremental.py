import os
import subprocess
from pathlib import Path

import pytest

from knowitall_graphify import GraphifyConfig, executable_digest
from knowitall_publication import PublicationStore
from knowitall_snapshot import SnapshotPolicy, create_snapshot
from knowitall_updates import UpdateLedger, UpdateRunner

RUNTIME = os.environ.get("KNOWITALL_GRAPHIFY_RUNTIME")
pytestmark = pytest.mark.skipif(not RUNTIME, reason="pinned runtime required")


def git(repo, *args):
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=repo, check=True, capture_output=True)


@pytest.mark.parametrize("fixture", ["python_service", "typescript_client"])
def test_real_incremental_noop_changed_renamed_deleted(make_repo, tmp_path, fixture, monkeypatch):
    repo = make_repo(fixture)
    interpreter = Path(RUNTIME) / "bin/python"
    config = GraphifyConfig(interpreter, python_path=str(Path(RUNTIME) / "lib/python3.14/site-packages"), expected_executable_digest=executable_digest(interpreter))
    ledger = UpdateLedger(tmp_path / "updates", PublicationStore(tmp_path / "store"))
    runner = UpdateRunner(ledger, config)
    def update(key, predecessor):
        snapshot = create_snapshot(repo, "p", "r", tmp_path / "snapshots", SnapshotPolicy())
        runner.submit(key, snapshot, expected_current=predecessor)
        status = runner.resume(key)
        assert status.receipt.generation.snapshot.commit == snapshot.commit
        return status.receipt.generation
    first = update("first", None)
    import knowitall_updates.runner as module
    original = module.extract_generation
    monkeypatch.setattr(module, "extract_generation", lambda *args: pytest.fail("identical snapshot must reuse checkpoint"))
    assert update("noop", first) == first
    monkeypatch.setattr(module, "extract_generation", original)
    git(repo, "commit", "--allow-empty", "-qm", "empty")
    unchanged_bytes = update("empty-commit", first)
    assert unchanged_bytes.snapshot.commit != first.snapshot.commit
    files = sorted(path for path in (repo / "src").iterdir() if path.is_file())
    target = files[-1]
    if fixture == "python_service":
        from knowitall_graphify import GenerationValidationError
        original_source = target.read_text()
        target.write_text("def new_symbol():\n    return 1\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "unresolved reference")
        with pytest.raises(GenerationValidationError):
            update("unresolved", unchanged_bytes)
        assert ledger.store.resolve_current("p", "r") == unchanged_bytes
        assert runner.ledger.inspect("unresolved").phase != "published"
        target.write_text(original_source)
    target.write_text(target.read_text() + ("\ndef added_symbol():\n    return 2\n" if fixture == "python_service" else "\nexport function addedSymbol() { return 2; }\n"))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "modify")
    changed = update("changed", unchanged_bytes)
    assert any(node.name in {"added_symbol()", "addedSymbol()"} for node in ledger.store.open_generation(changed).nodes)
    renamed_path = target.with_name("renamed" + target.suffix)
    git(repo, "mv", str(target.relative_to(repo)), str(renamed_path.relative_to(repo)))
    if fixture == "python_service":
        for path in (repo / "src").glob("*.py"):
            path.write_text(path.read_text().replace(".store import", ".renamed import"))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "rename")
    renamed = update("renamed", changed)
    graph = ledger.store.open_generation(renamed)
    assert all(node.path != str(target.relative_to(repo)) for node in graph.nodes)
    assert any(node.path == str(renamed_path.relative_to(repo)) for node in graph.nodes)
    git(repo, "rm", str(renamed_path.relative_to(repo)))
    for path in (repo / "src").iterdir():
        if path.is_file():
            path.write_text("def remaining():\n    return 1\n" if fixture == "python_service" else "export function remaining() { return 1; }\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "delete")
    deleted = update("deleted", renamed)
    assert all(node.path != str(renamed_path.relative_to(repo)) for node in ledger.store.open_generation(deleted).nodes)
    assert runner.resume("first").receipt.generation == first
    assert ledger.store.resolve_current("p", "r") == deleted
