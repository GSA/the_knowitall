import json
from dataclasses import replace

import pytest

from knowitall_updates import UpdateConflict, UpdateInterrupted
from test_runner import runner


def test_request_acknowledgment_ambiguity_reopens_saved_request(generation_factory, tmp_path, monkeypatch):
    generation, snapshot = generation_factory()
    instance = runner(tmp_path, monkeypatch, generation)
    import knowitall_updates.ledger as module
    original = module.fsync_directory
    def fail_after_rename(path):
        original(path)
        if path.name == "requests":
            raise OSError("lost acknowledgment")
    monkeypatch.setattr(module, "fsync_directory", fail_after_rename)
    with pytest.raises(OSError):
        instance.submit("a", snapshot, expected_current=None)
    monkeypatch.setattr(module, "fsync_directory", original)
    assert instance.submit("a", snapshot, expected_current=None).phase == "requested"
    assert instance.resume("a").phase == "published"


def test_fatal_extraction_is_retryable_and_not_complete(generation_factory, tmp_path, monkeypatch):
    generation, snapshot = generation_factory()
    instance = runner(tmp_path, monkeypatch, generation)
    import knowitall_updates.runner as module
    original = module.extract_generation
    def fail(*args):
        raise RuntimeError("parser process crashed")
    monkeypatch.setattr(module, "extract_generation", fail)
    instance.submit("a", snapshot, expected_current=None)
    with pytest.raises(RuntimeError):
        instance.resume("a")
    assert instance.ledger.inspect("a").phase == "extracting"
    with pytest.raises(KeyError):
        instance.ledger.store.resolve_current("project-a", "repo-a")
    monkeypatch.setattr(module, "extract_generation", original)
    assert instance.resume("a").phase == "published"


def test_changed_runtime_cannot_resume_acknowledged_request(generation_factory, tmp_path, monkeypatch):
    generation, snapshot = generation_factory()
    instance = runner(tmp_path, monkeypatch, generation)
    instance.submit("a", snapshot, expected_current=None)
    import knowitall_updates.runner as module
    monkeypatch.setattr(module, "runtime_identities", lambda config: ("other", "other", "other"))
    with pytest.raises(UpdateConflict):
        instance.resume("a")


@pytest.mark.parametrize("name", ["artifact.bin", "metadata.json", "metadata.sha256"])
def test_missing_current_evidence_blocks_extraction_from_empty_predecessor(generation_factory, tmp_path, monkeypatch, name):
    from knowitall_publication import PublicationValidationError
    import knowitall_updates.runner as module

    generation, snapshot = generation_factory()
    instance = runner(tmp_path, monkeypatch, generation)
    store = instance.ledger.store
    store.publish(store.stage(generation))
    pointer = next((store.root / "current").iterdir())
    original = pointer.read_bytes()
    next((store.root / "generations").glob("*/" + name)).unlink()
    instance.submit("empty-predecessor", snapshot, expected_current=None)
    monkeypatch.setattr(module, "extract_generation", lambda *args: pytest.fail("missing selected evidence must block extraction"))

    with pytest.raises(PublicationValidationError):
        instance.resume("empty-predecessor")
    status = instance.ledger.inspect("empty-predecessor")
    assert status.phase == "requested"
    assert status.reasons == ((".", "PublicationValidationError"),)
    assert not (instance.ledger.root / "workspace").exists()
    assert pointer.read_bytes() == original


@pytest.mark.parametrize("failpoint", ["after_checkpoint", "after_stage", "before_current_replace", "after_current_replace"])
def test_repeated_resume_reconciles_interrupted_publication(generation_factory, tmp_path, monkeypatch, failpoint):
    from knowitall_publication import PublicationInterrupted
    generation, snapshot = generation_factory()
    instance = runner(tmp_path, monkeypatch, generation)
    instance.submit("a", snapshot, expected_current=None)
    with pytest.raises((UpdateInterrupted, PublicationInterrupted)):
        instance.resume("a", failpoint=failpoint)
    status = instance.resume("a")
    assert status.phase == "published"
    assert instance.resume("a").receipt == status.receipt
