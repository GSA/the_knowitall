from dataclasses import replace

import pytest

from knowitall_contract import SourceRange
from knowitall_publication import PublicationStore, PublicationValidationError


@pytest.mark.parametrize("mutation", ["range", "edge_kind", "edge_target"])
def test_publication_rejects_normalized_evidence_not_bound_to_raw(generation_factory, tmp_path, mutation):
    generation, _ = generation_factory()
    if mutation == "range":
        generation = replace(generation, nodes=(replace(generation.nodes[0], source_range=SourceRange(80, 1, 81, 1)), *generation.nodes[1:]))
    else:
        edge = generation.edges[0]
        edge = replace(edge, kind="invented") if mutation == "edge_kind" else replace(edge, target=edge.source)
        generation = replace(generation, edges=(edge, *generation.edges[1:]))
    store = PublicationStore(tmp_path)
    with pytest.raises(PublicationValidationError):
        store.publish(store.stage(generation))
