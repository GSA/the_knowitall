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
