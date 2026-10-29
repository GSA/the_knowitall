import json

import pytest

from knowitall_graphify import normalize_generation
from knowitall_publication import PublicationStore, PublicationValidationError, authoritative_deletions
from knowitall_updates import UpdateLedger, UpdateValidationError
from dataclasses import replace


def test_checkpoint_preserves_and_validates_companions(generation_factory, tmp_path):
    from knowitall_updates import checkpoint
    generation, snapshot = generation_factory()
    ledger = UpdateLedger(tmp_path / "updates", PublicationStore(tmp_path / "store"))
    ledger.submit("a", snapshot, expected_current=None, engine_identity=generation.engine_identity, runtime_identity=generation.runtime_identity, config_identity=generation.config_identity)
    output = tmp_path / "output" / "graphify-out"
    output.mkdir(parents=True)
    (output / "graph.json").write_bytes(generation.raw_artifact)
    (output / "manifest.json").write_text("{}")
    checkpoint.commit(ledger, "a", output.parent, generation)
    assert checkpoint.load(ledger, "a") == generation
    (ledger.request_path("a") / "checkpoint" / "manifest.json").write_text('{"altered":1}')
    with pytest.raises(UpdateValidationError):
        checkpoint.load(ledger, "a")


def test_deletion_authority_cannot_cross_repository(generation_factory):
    _, previous = generation_factory()
    other = replace(previous, repository_id="other", included=())
    with pytest.raises(PublicationValidationError):
        authoritative_deletions(previous, other)
