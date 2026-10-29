from dataclasses import replace

import pytest

from knowitall_publication import PublicationStore
from knowitall_updates import UpdateLedger
from knowitall_graphify import GraphifyConfig


def runner(tmp_path, monkeypatch, generation):
    from knowitall_updates import UpdateRunner
    import knowitall_updates.runner as module
    monkeypatch.setattr(module, "runtime_identities", lambda config: (generation.engine_identity, generation.runtime_identity, generation.config_identity))
    def extract(snapshot, source, output, config):
        path = output / "graphify-out"
        path.mkdir(parents=True, exist_ok=True)
        (path / "graph.json").write_bytes(generation.raw_artifact)
        (path / "manifest.json").write_text("{}")
        return generation
    monkeypatch.setattr(module, "extract_generation", extract)
    ledger = UpdateLedger(tmp_path / "updates", PublicationStore(tmp_path / "store"))
    return UpdateRunner(ledger, GraphifyConfig(executable=tmp_path / "python"))


def test_staged_restart_does_not_extract_again(generation_factory, tmp_path, monkeypatch):
    from knowitall_updates import UpdateInterrupted
    generation, snapshot = generation_factory()
    instance = runner(tmp_path, monkeypatch, generation)
    instance.submit("a", snapshot, expected_current=None)
    with pytest.raises(UpdateInterrupted):
        instance.resume("a", failpoint="after_checkpoint")
    import knowitall_updates.runner as module
    monkeypatch.setattr(module, "extract_generation", lambda *args: pytest.fail("checkpoint must avoid extraction"))
    status = instance.resume("a")
    assert status.phase == "published"
    assert status.receipt.generation.snapshot.commit == snapshot.commit
    assert instance.resume("a") == status


def test_incomplete_inventory_blocks_without_selecting_empty_graph(generation_factory, tmp_path, monkeypatch):
    generation, snapshot = generation_factory()
    instance = runner(tmp_path, monkeypatch, generation)
    predecessor = instance.ledger.store.publish(instance.ledger.store.stage(generation)).generation
    incomplete = replace(snapshot, inventory_complete=False, failed=({"path": ".", "reason": "inventory_listing_failed"},))
    instance.submit("b", incomplete, expected_current=predecessor)
    status = instance.resume("b")
    assert status.phase == "blocked"
    assert status.reasons == ((".", "inventory_listing_failed"),)
    assert instance.ledger.store.resolve_current("project-a", "repo-a") == predecessor
