import multiprocessing
import os
import json

from knowitall_graphify import normalize_generation
from knowitall_publication import PublicationConflict, PublicationStore


def _publish(root, generation, predecessor, barrier, result):
    store = PublicationStore(root)
    staged = store.stage(generation)
    barrier.wait()
    try:
        store.publish(staged, expected_current=predecessor)
        result.put("published")
    except PublicationConflict:
        result.put("conflict")


def test_two_processes_cannot_select_from_same_predecessor(generation_factory, tmp_path):
    first, snapshot = generation_factory()
    raw = json.loads(first.raw_artifact)
    raw["nodes"][0]["name"] = "second"
    second = normalize_generation(snapshot, json.dumps(raw).encode())
    raw["nodes"][0]["name"] = "third"
    third = normalize_generation(snapshot, json.dumps(raw).encode())
    store = PublicationStore(tmp_path / "store")
    predecessor = store.publish(store.stage(first)).generation
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(2), ctx.Queue()
    processes = [ctx.Process(target=_publish, args=(store.root, generation, predecessor, barrier, results)) for generation in (second, third)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(15)
        if process.is_alive():
            process.kill()
            process.join()
        assert process.exitcode == 0
    assert sorted([results.get(timeout=3), results.get(timeout=3)]) == ["conflict", "published"]


def _die_after_replace(root, generation):
    import knowitall_publication.store as module
    original = module.os.replace
    def replace(source, destination):
        original(source, destination)
        if destination.parent.name == "current":
            os._exit(91)
    module.os.replace = replace
    store = PublicationStore(root)
    store.publish(store.stage(generation))


def test_abrupt_death_after_replace_reconciles_without_rollback(generation_factory, tmp_path):
    first, _ = generation_factory()
    second, _ = generation_factory(fixture="typescript_client")
    root = tmp_path / "store"
    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=_die_after_replace, args=(root, first))
    child.start()
    child.join(15)
    if child.is_alive():
        child.kill()
        child.join()
    assert child.exitcode == 91
    store = PublicationStore(root)
    receipt = store.publish(store.resume(first.generation_id))
    store.publish(store.stage(second))
    assert store.publish(store.resume(first.generation_id)) == receipt
    assert store.resolve_current("project-a", "repo-a").generation_id == second.generation_id
