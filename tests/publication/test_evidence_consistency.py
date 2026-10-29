import json

import pytest

from knowitall_publication import PublicationStore, PublicationValidationError


@pytest.mark.parametrize("field", ["range", "edge", "digest", "snapshot"])
def test_persisted_evidence_cannot_change_independently_of_artifact(generation_factory, tmp_path, field):
    generation, _ = generation_factory()
    store = PublicationStore(tmp_path / "store")
    reference = store.publish(store.stage(generation)).generation
    path = next((store.root / "generations").glob("*/metadata.json"))
    value = json.loads(path.read_bytes())
    if field == "range":
        value["nodes"][0]["source_range"]["start_line"] = 2
        value["nodes"][0]["source_range"]["end_line"] = 3
    elif field == "edge":
        value["edges"][0]["kind"] = "imports"
    elif field == "digest":
        value["nodes"][0]["content_digest"] = "sha256:" + "0" * 64
    else:
        value["snapshot"]["commit"] = "invented-commit"
    path.write_text(json.dumps(value))
    with pytest.raises(PublicationValidationError):
        store.open_generation(reference)
