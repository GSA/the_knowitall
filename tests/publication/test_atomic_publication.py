from dataclasses import replace
import json
import hashlib

import pytest

from knowitall_contract import GenerationRef
from knowitall_graphify import GraphEdge
from knowitall_publication import PublicationConflict, PublicationStore, PublicationValidationError


def ref(generation):
    return GenerationRef(generation.snapshot, generation.generation_id, generation.artifact_digest)


def test_staging_is_durable_but_not_queryable(generation_factory, tmp_path):
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path / "store")

    staged = store.stage(generation)

    with pytest.raises(KeyError):
        store.resolve_current("project-a", "repo-a")
    with pytest.raises(KeyError):
        store.open_generation(ref(generation))
    assert PublicationStore(tmp_path / "store").resume(staged.stage_id).generation_id == generation.generation_id


def test_publish_atomically_selects_and_opens_generation(generation_factory, tmp_path):
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path / "store")

    receipt = store.publish(store.stage(generation))

    assert receipt.generation == ref(generation)
    assert store.resolve_current("project-a", "repo-a") == ref(generation)
    assert store.open_generation(ref(generation)) == generation


def test_opaque_identity_text_never_becomes_a_filesystem_path(generation_factory, tmp_path):
    generation, _ = generation_factory(project="../../project", repository="repo/../escape")
    store = PublicationStore(tmp_path / "store")

    store.publish(store.stage(generation))

    assert store.resolve_current("../../project", "repo/../escape") == ref(generation)
    assert all(path.resolve().is_relative_to(store.root.resolve()) for path in store.root.rglob("*"))


def test_current_selection_is_isolated_per_project_and_repository(generation_factory, tmp_path):
    first, _ = generation_factory(project="project-a", repository="repo-a")
    second, _ = generation_factory(project="project-a", repository="repo-b")
    third, _ = generation_factory(project="project-b", repository="repo-a")
    store = PublicationStore(tmp_path / "store")
    for generation in (first, second, third):
        store.publish(store.stage(generation))

    assert store.resolve_current("project-a", "repo-a") == ref(first)
    assert store.resolve_current("project-a", "repo-b") == ref(second)
    assert store.resolve_current("project-b", "repo-a") == ref(third)


def test_exact_retry_is_idempotent_but_same_identity_different_bytes_conflicts(generation_factory, tmp_path):
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path / "store")
    first = store.publish(store.stage(generation))

    retry = store.publish(store.stage(generation))
    assert retry == first

    conflicting = replace(generation, raw_artifact=generation.raw_artifact + b" ")
    with pytest.raises(PublicationConflict):
        store.stage(conflicting)


def test_publish_rejects_tampered_persisted_artifact(generation_factory, tmp_path):
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path / "store")
    staged = store.stage(generation)
    artifact = next((tmp_path / "store" / "stages").glob("*/artifact.bin"))
    artifact.write_bytes(generation.raw_artifact + b"tampered")

    with pytest.raises(PublicationValidationError, match="artifact digest"):
        store.publish(staged)


def test_publish_rejects_tampered_normalized_evidence(generation_factory, tmp_path):
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path / "store")
    staged = store.stage(generation)
    metadata_path = next((tmp_path / "store" / "stages").glob("*/metadata.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["nodes"][0]["content_digest"] = "sha256:" + "0" * 64
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    metadata_path.with_name("metadata.sha256").write_text(hashlib.sha256(metadata_path.read_bytes()).hexdigest())

    with pytest.raises(PublicationValidationError, match="generation identity"):
        store.publish(staged)


def test_publish_revalidates_artifact_endpoints_and_coverage(generation_factory, tmp_path):
    generation, _ = generation_factory()
    bad_edge = replace(generation.edges[0], target="missing")
    invalid = replace(generation, edges=(bad_edge,))
    store = PublicationStore(tmp_path / "store")

    staged = store.stage(invalid)
    with pytest.raises(PublicationValidationError, match="dangling"):
        store.publish(staged)
    with pytest.raises(KeyError):
        store.resolve_current("project-a", "repo-a")
