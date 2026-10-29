import hashlib
import json
import stat
import threading
from dataclasses import replace
from pathlib import Path

import pytest

import knowitall_spud.store as store_module
from knowitall_spud.records import normalize_bundle
from knowitall_spud.store import (
    AdmissionConflict,
    AdmissionInterrupted,
    AdmissionStore,
    AdmissionValidationError,
)

from knowitall_spud.store import _receipt as _receipt_of

from conftest import GRAPH_PATH, GRAPH_REPORT_PATH, normalize_bundle_at


def _receipt_digest(bundle):
    return _receipt_of(bundle).receipt_digest


def test_admit_persists_bytes_and_returns_stable_receipt(tmp_path, admitted_bundle):
    store, bundle, receipt = admitted_bundle()

    assert receipt.receipt_digest.startswith("sha256:")
    assert len(receipt.receipt_digest) == len("sha256:") + 64
    assert receipt.reader_profile == "spud-reader/v1"
    assert dict(receipt.artifact_digests) == {item.path: item.content_digest for item in bundle.artifacts}
    assert receipt.revision_binding == bundle.revision_binding
    assert receipt.artifact_completeness == bundle.artifact_completeness
    assert receipt.limitations == bundle.limitations

    stored = [
        path.read_bytes()
        for path in (store.root / "bundles").rglob("artifacts/*")
        if path.is_file()
    ]
    for artifact in bundle.artifacts:
        assert artifact.data in stored


def test_exact_retry_returns_identical_receipt(tmp_path, admitted_bundle):
    store, bundle, receipt = admitted_bundle()

    assert store.admit(bundle) == receipt


def test_exact_retry_after_reopening_store_returns_identical_receipt(tmp_path, admitted_bundle):
    store, bundle, receipt = admitted_bundle()

    assert AdmissionStore(store.root).admit(bundle) == receipt


def test_changed_artifact_bytes_conflict(tmp_path, admitted_bundle, make_bundle):
    store, _bundle, _receipt = admitted_bundle()
    changed_root, changed_value = make_bundle()
    (changed_root / GRAPH_REPORT_PATH).write_text("# Different report\n\nChanged bytes.\n", encoding="utf-8")

    with pytest.raises(AdmissionConflict, match="different retained bytes"):
        store.admit(normalize_bundle_at(changed_root, changed_value))


def test_changed_metadata_conflicts(tmp_path, admitted_bundle, make_bundle):
    store, _bundle, _receipt = admitted_bundle()
    other_root, other_value = make_bundle(supplied={"generator_version": "spud other-revision"})

    with pytest.raises(AdmissionConflict, match="different retained metadata"):
        store.admit(normalize_bundle_at(other_root, other_value))


def test_added_companion_requires_new_bundle_id(tmp_path, admitted_bundle, make_bundle):
    store, _bundle, receipt = admitted_bundle(citation_index=False)
    richer_root, richer_value = make_bundle(citation_index=True)

    with pytest.raises(AdmissionConflict):
        store.admit(normalize_bundle_at(richer_root, richer_value))

    reopened, reopened_receipt = store.open_bundle("project-a", "repo-a", "bundle-1")
    assert reopened_receipt == receipt
    assert all(item.role != "citation_index" for item in reopened.artifacts)

    richer_value["bundle_id"] = "bundle-2"
    fresh = store.admit(normalize_bundle_at(richer_root, richer_value))
    assert fresh.bundle_id == "bundle-2"
    assert fresh.receipt_digest != receipt.receipt_digest
    assert store.list_bundles("project-a", "repo-a") == ("bundle-1", "bundle-2")


@pytest.mark.parametrize("failpoint", ["before_persist", "after_persist", "before_pointer"])
def test_interrupted_admission_is_not_queryable(tmp_path, admitted_bundle, failpoint):
    store = AdmissionStore(tmp_path / f"admissions-{failpoint}")

    with pytest.raises(AdmissionInterrupted, match=failpoint):
        admitted_bundle(store=store, failpoint=failpoint)

    with pytest.raises(KeyError):
        store.open_bundle("project-a", "repo-a", "bundle-1")
    assert store.list_bundles("project-a", "repo-a") == ()
    assert store.recover() == ()
    assert not any(path.name.startswith(".admit-") for path in (store.root / "bundles").iterdir())


def test_corrupted_retained_artifact_fails_readback(tmp_path, admitted_bundle):
    store, bundle, _receipt = admitted_bundle()
    target = next(
        path
        for path in (store.root / "bundles").rglob("artifacts/*")
        if path.is_file() and path.read_bytes() == next(item.data for item in bundle.artifacts if item.path == GRAPH_PATH)
    )
    target.write_bytes(b'{"nodes": [], "edges": []}')

    with pytest.raises(AdmissionValidationError, match="digest mismatch"):
        store.open_bundle("project-a", "repo-a", "bundle-1")


def test_open_bundle_round_trips_records_and_limitations(tmp_path, admitted_bundle):
    store, bundle, receipt = admitted_bundle(citation_index=True, report=False)

    reopened, reopened_receipt = store.open_bundle("project-a", "repo-a", "bundle-1")

    assert reopened == bundle
    assert reopened_receipt == receipt
    assert reopened.limitations == bundle.limitations
    assert reopened.records == bundle.records


def test_bundles_are_isolated_per_project_and_repository(tmp_path, admitted_bundle, make_bundle):
    store, _bundle, receipt = admitted_bundle()
    other_root, other_value = make_bundle(project="project-b", repository="repo-b")
    other = store.admit(normalize_bundle_at(other_root, other_value))

    assert store.list_bundles("project-a", "repo-a") == ("bundle-1",)
    assert store.list_bundles("project-b", "repo-b") == ("bundle-1",)
    assert other.receipt_digest != receipt.receipt_digest
    with pytest.raises(KeyError):
        store.open_bundle("project-a", "repo-b", "bundle-1")


def test_store_paths_are_hash_derived_and_private(tmp_path, admitted_bundle, make_bundle):
    store, _bundle, _receipt = admitted_bundle()
    escape_root, escape_value = make_bundle(bundle_id="../escape")
    receipt = store.admit(normalize_bundle_at(escape_root, escape_value))

    assert receipt.bundle_id == "../escape"
    assert not (tmp_path / "escape").exists()
    reopened, _ = store.open_bundle("project-a", "repo-a", "../escape")
    assert reopened.bundle_id == "../escape"
    for path in (store.root, store.root / "bundles", store.root / "index"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    names = {path.name for path in (store.root / "bundles").iterdir()}
    assert all(len(name) == 64 and all(char in "0123456789abcdef" for char in name) for name in names)


def test_admit_rejects_an_artifact_whose_digest_does_not_match_its_bytes(tmp_path, admitted_bundle):
    store, bundle, _receipt = admitted_bundle(admit=False)
    artifacts = tuple(
        replace(item, content_digest="sha256:" + "0" * 64) if item.role == "graph" else item
        for item in bundle.artifacts
    )

    with pytest.raises(AdmissionValidationError, match="digest mismatch"):
        store.admit(replace(bundle, artifacts=artifacts))

    assert store.list_bundles("project-a", "repo-a") == ()


def test_missing_retained_artifact_is_reported_as_validation_failure(tmp_path, admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    target = next(path for path in (store.root / "bundles").rglob("artifacts/*") if path.is_file())
    target.unlink()

    with pytest.raises(AdmissionValidationError, match="missing retained artifact"):
        store.open_bundle("project-a", "repo-a", "bundle-1")


def test_readmitting_over_an_unreadable_bundle_fails_loudly(tmp_path, admitted_bundle):
    store, bundle, _receipt = admitted_bundle()
    directory = next(path for path in (store.root / "bundles").iterdir() if path.is_dir())
    (directory / "receipt.json").unlink()

    with pytest.raises(AdmissionValidationError, match="cannot be read"):
        store.admit(bundle)


def test_retained_files_are_owner_readable_only(tmp_path, admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()

    files = [path for path in store.root.rglob("*") if path.is_file()]
    assert files
    for path in files:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_tampered_pointer_cannot_escape_the_bundle_directory(tmp_path, admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    pointer = next(path for path in (store.root / "index").rglob("*") if path.is_file())
    pointer.write_bytes(json.dumps({"bundle_id": "bundle-1", "bundle_key": "../../../etc"}).encode())

    with pytest.raises(KeyError):
        store.open_bundle("project-a", "repo-a", "bundle-1")


def test_recover_reports_healthy_bundles_and_removes_unreferenced_directories(tmp_path, admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    orphan = store.root / "bundles" / ("a" * 64)
    orphan.mkdir()
    (orphan / "metadata.json").write_bytes(b"{}")

    assert store.recover() == ("bundle-1",)
    assert not orphan.exists()
    assert store.open_bundle("project-a", "repo-a", "bundle-1")[1].bundle_id == "bundle-1"


def damage(store):
    directory = next(path for path in (store.root / "bundles").iterdir() if path.is_dir())
    (directory / "receipt.json").unlink()
    return directory


def test_damaged_bundles_are_reported_rather_than_silently_skipped(tmp_path, admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    directory = damage(store)

    assert store.recover() == ()
    assert directory.exists()
    assert store.damaged_bundles() == (("project-a", "repo-a", "bundle-1"),)


def test_discarding_a_damaged_bundle_allows_re_admission(tmp_path, admitted_bundle):
    store, bundle, receipt = admitted_bundle()
    directory = damage(store)

    store.discard_damaged("project-a", "repo-a", "bundle-1")

    assert not directory.exists()
    assert store.damaged_bundles() == ()
    assert store.list_bundles("project-a", "repo-a") == ()
    assert store.admit(bundle) == receipt


def test_discard_refuses_to_remove_a_readable_bundle(tmp_path, admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()

    with pytest.raises(AdmissionConflict, match="is readable"):
        store.discard_damaged("project-a", "repo-a", "bundle-1")

    assert store.list_bundles("project-a", "repo-a") == ("bundle-1",)


def metadata_path(store):
    directory = next(path for path in (store.root / "bundles").iterdir() if path.is_dir())
    return directory / "metadata.json"


def test_read_back_rejects_a_record_edited_without_changing_its_id(tmp_path, admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    path = metadata_path(store)
    value = json.loads(path.read_bytes())
    narrative = next(item for item in value["records"] if item["kind"] == "narrative_passage")
    narrative["text"] = "substituted narrative text"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(AdmissionValidationError, match="receipt does not match"):
        store.open_bundle("project-a", "repo-a", "bundle-1")


def test_read_back_rejects_substituted_supplied_provenance(tmp_path, admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    path = metadata_path(store)
    value = json.loads(path.read_bytes())
    value["supplied"] = dict(value["supplied"], generator_version="graphifyy==9.9.9")
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(AdmissionValidationError, match="receipt does not match"):
        store.open_bundle("project-a", "repo-a", "bundle-1")


def test_structurally_damaged_metadata_is_reported_as_damage(tmp_path, admitted_bundle):
    store, bundle, receipt = admitted_bundle()
    path = metadata_path(store)
    value = json.loads(path.read_bytes())
    value["records"] = None
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(AdmissionValidationError):
        store.open_bundle("project-a", "repo-a", "bundle-1")
    assert store.damaged_bundles() == (("project-a", "repo-a", "bundle-1"),)

    store.discard_damaged("project-a", "repo-a", "bundle-1")
    assert store.admit(bundle) == receipt


@pytest.mark.parametrize("payload", ["null", "[]", '"text"', '{"bundle_id": "bundle-1"}'])
def test_structurally_damaged_pointers_are_absence_not_a_crash(tmp_path, admitted_bundle, payload):
    store, _bundle, _receipt = admitted_bundle()
    index = next(path for path in (store.root / "index").iterdir() if path.is_dir())
    pointer = next(path for path in index.iterdir() if not path.name.startswith("."))
    pointer.write_text(payload, encoding="utf-8")

    with pytest.raises(KeyError):
        store.open_bundle("project-a", "repo-a", "bundle-1")
    assert store.list_bundles("project-a", "repo-a") == ()
    assert store.damaged_bundles() == ()
    assert store.recover() == ()


@pytest.mark.parametrize("name", ["metadata.json", "receipt.json"])
def test_undecodable_persisted_json_is_reported_as_damage(tmp_path, admitted_bundle, name):
    store, bundle, receipt = admitted_bundle()
    metadata_path(store).with_name(name).write_bytes(b'{"bundle_id": "\xff"}')

    with pytest.raises(AdmissionValidationError):
        store.open_bundle("project-a", "repo-a", "bundle-1")
    assert store.damaged_bundles() == (("project-a", "repo-a", "bundle-1"),)

    store.discard_damaged("project-a", "repo-a", "bundle-1")
    assert store.admit(bundle) == receipt


def test_undecodable_pointer_bytes_are_absence_not_a_crash(tmp_path, admitted_bundle):
    store, _bundle, _receipt = admitted_bundle()
    index = next(path for path in (store.root / "index").iterdir() if path.is_dir())
    pointer = next(path for path in index.iterdir() if not path.name.startswith("."))
    pointer.write_bytes(b'{"bundle_id": "\xff"}')

    with pytest.raises(KeyError):
        store.open_bundle("project-a", "repo-a", "bundle-1")
    assert store.list_bundles("project-a", "repo-a") == ()
    assert store.damaged_bundles() == ()
    assert store.recover() == ()


def test_metadata_with_a_null_artifact_path_is_reported_as_damage(tmp_path, admitted_bundle):
    store, bundle, receipt = admitted_bundle()
    path = metadata_path(store)
    value = json.loads(path.read_bytes())
    value["artifacts"][0]["path"] = None
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(AdmissionValidationError):
        store.open_bundle("project-a", "repo-a", "bundle-1")
    assert store.damaged_bundles() == (("project-a", "repo-a", "bundle-1"),)

    store.discard_damaged("project-a", "repo-a", "bundle-1")
    assert store.admit(bundle) == receipt


def test_a_new_index_directory_is_persisted_before_acknowledgement(tmp_path, admitted_bundle, monkeypatch):
    synced = []
    monkeypatch.setattr(store_module, "_fsync_directory", lambda path: synced.append(Path(path)))

    target, bundle, _receipt = admitted_bundle(store=AdmissionStore(tmp_path / "fresh"))
    index_root = target.root / "index"

    project_index = target._index_path("project-a", "repo-a")
    assert index_root in synced
    assert synced.index(index_root) < synced.index(project_index)
    synced.clear()
    target.admit(bundle)
    # An existing index directory may be a mkdir left by an interrupted
    # admission, so its entry is persisted on republication too.
    assert synced.index(index_root) < synced.index(project_index)


def test_a_new_store_root_persists_every_created_ancestor(tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr(store_module, "_fsync_directory", lambda path: synced.append(Path(path)))
    root = tmp_path / "outer" / "inner" / "store"

    store = AdmissionStore(root)

    assert store.root == root
    for created in (tmp_path / "outer", tmp_path / "outer" / "inner", root, root / "bundles", root / "index"):
        assert created.parent in synced, created
    assert synced.index(tmp_path) < synced.index(tmp_path / "outer") < synced.index(root)


def test_recovery_cannot_reclaim_a_bundle_mid_admission(tmp_path, make_bundle, monkeypatch):
    store = AdmissionStore(tmp_path / "admissions")
    bundle = normalize_bundle_at(*make_bundle())
    publish = AdmissionStore._publish_pointer
    recovered = []
    workers = []

    def interleaved(self, value):
        worker = threading.Thread(target=lambda: recovered.append(AdmissionStore(self.root).recover()))
        workers.append(worker)
        worker.start()
        worker.join(0.5)
        # Recovery waits for the admission instead of reclaiming its retained bytes.
        assert worker.is_alive()
        publish(self, value)

    monkeypatch.setattr(AdmissionStore, "_publish_pointer", interleaved)
    receipt = store.admit(bundle)
    for worker in workers:
        worker.join(5)
        assert not worker.is_alive()

    assert recovered == [("bundle-1",)]
    assert store.open_bundle("project-a", "repo-a", "bundle-1")[1] == receipt


def test_a_changed_unverified_binding_assertion_conflicts(tmp_path, admitted_bundle, make_bundle):
    binding = {"commit_sha": "4" * 40, "graph_digest": "sha256:" + "0" * 64}
    store, _bundle, receipt = admitted_bundle(source_binding=binding)
    other_root, other_value = make_bundle(
        source_binding={"commit_sha": "5" * 40, "graph_digest": "sha256:" + "0" * 64}
    )
    other = normalize_bundle_at(other_root, other_value)

    assert _receipt_digest(other) != receipt.receipt_digest
    with pytest.raises(AdmissionConflict, match="different retained metadata"):
        store.admit(other)
    assert store.open_bundle("project-a", "repo-a", "bundle-1")[0].supplied_binding == binding


def test_reopening_persists_directories_left_by_an_interrupted_initialization(tmp_path, monkeypatch):
    root = tmp_path / "store"
    for path in (root, root / "bundles", root / "index"):
        path.mkdir(mode=0o700)  # mkdir without the parent fsync that follows it
    synced = []
    monkeypatch.setattr(store_module, "_fsync_directory", lambda path: synced.append(Path(path)))

    AdmissionStore(root)

    assert synced.count(root) >= 2
    assert tmp_path in synced


def test_concurrent_construction_of_a_fresh_store_succeeds(tmp_path):
    root = tmp_path / "shared"
    barrier = threading.Barrier(4)
    failures = []

    def construct():
        barrier.wait(5)
        try:
            AdmissionStore(root)
        except Exception as error:  # noqa: BLE001 - the failure itself is the finding
            failures.append(error)

    workers = [threading.Thread(target=construct) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)

    assert failures == []
    assert (root / "bundles").is_dir() and (root / "index").is_dir()
