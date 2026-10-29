import multiprocessing
import os

from knowitall_graphify import GraphifyConfig
from knowitall_publication import PublicationStore
from knowitall_updates import UpdateLedger, UpdateRunner


def _run(root, snapshot, generation, die):
    import knowitall_updates.runner as module
    module.runtime_identities = lambda config: (generation.engine_identity, generation.runtime_identity, generation.config_identity)
    def extract(snapshot, source, output, config):
        path = output / "graphify-out"
        path.mkdir(parents=True, exist_ok=True)
        (path / "graph.json").write_bytes(b"half-written" if die else generation.raw_artifact)
        (path / "manifest.json").write_text("{}")
        if die:
            os._exit(92)
        return generation
    module.extract_generation = extract
    ledger = UpdateLedger(root / "updates", PublicationStore(root / "store"))
    runner = UpdateRunner(ledger, GraphifyConfig(root / "python"))
    runner.submit("a", snapshot, expected_current=None)
    assert runner.resume("a").phase == "published"


def test_process_death_does_not_reuse_half_written_extraction(generation_factory, tmp_path):
    generation, snapshot = generation_factory()
    ctx = multiprocessing.get_context("spawn")
    for die, expected in ((True, 92), (False, 0)):
        child = ctx.Process(target=_run, args=(tmp_path, snapshot, generation, die))
        child.start()
        child.join(15)
        if child.is_alive():
            child.kill()
            child.join()
        assert child.exitcode == expected
    store = PublicationStore(tmp_path / "store")
    reference = store.resolve_current("project-a", "repo-a")
    assert store.open_generation(reference).raw_artifact == generation.raw_artifact
