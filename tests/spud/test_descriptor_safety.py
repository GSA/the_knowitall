import hashlib
import json
import os

import pytest

from knowitall_spud.artifacts import ArtifactError, read_bundle, safe_relative_path
from knowitall_spud.descriptor import (
    BundleLimits,
    DescriptorError,
    SelectedArtifact,
    load_descriptor,
    resolve_artifacts,
)



def test_load_descriptor_rejects_unknown_version(make_bundle):
    _root, value = make_bundle()
    value["descriptor_version"] = "knowitall.spud-admission/v2"

    with pytest.raises(DescriptorError, match="descriptor version"):
        load_descriptor(value)


def test_load_descriptor_requires_identity_and_bundle_id(make_bundle):
    _root, value = make_bundle()
    del value["project_id"]

    with pytest.raises(DescriptorError, match="project_id"):
        load_descriptor(value)


def test_resolve_artifacts_auto_selects_current_layout(make_bundle):
    root, value = make_bundle(layout="auto", citation_index=True)

    selected, limitations = resolve_artifacts(root, load_descriptor(value), BundleLimits())

    roles = {item.role for item in selected}
    assert {"graph", "graph_report", "article"} <= roles
    assert SelectedArtifact("article", "spud-out/markdown/analysis/structural-analysis.md") in selected
    assert limitations == ()


def test_resolve_artifacts_auto_rejects_ambiguous_layout(tmp_path, make_bundle):
    root, value = make_bundle(layout="auto")
    (root / "spud-out" / "legacy-article.md").write_text("# Legacy article\n", encoding="utf-8")

    with pytest.raises(DescriptorError, match="ambiguous"):
        resolve_artifacts(root, load_descriptor(value), BundleLimits())


def test_resolve_artifacts_reports_declared_and_detected_missing(make_bundle):
    root, value = make_bundle(report=False)
    value["declared_missing"] = [["spud-out/json/analysis/inputs/graph-index.json", "missing_citation_index"]]

    _selected, limitations = resolve_artifacts(root, load_descriptor(value), BundleLimits())

    assert ("graphify-out/GRAPH_REPORT.md", "missing_graph_report") in limitations
    assert ("spud-out/json/analysis/inputs/graph-index.json", "missing_citation_index") in limitations


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../outside.md", "C:\\graph.json", "a\\b.md", "spud-out//x.md", "spud-out/./x.md", ""],
)
def test_safe_relative_path_rejects(path):
    with pytest.raises(ArtifactError, match="unsafe bundle path"):
        safe_relative_path(path)


def test_read_bundle_rejects_symlink_and_fifo(tmp_path, make_bundle):
    root, value = make_bundle(layout="explicit")
    descriptor = load_descriptor(value)
    link = root / "graphify-out" / "linked.md"
    link.symlink_to(root / "graphify-out" / "GRAPH_REPORT.md")
    with_symlink = descriptor.artifacts + (SelectedArtifact("article", "graphify-out/linked.md"),)

    with pytest.raises(ArtifactError, match="not a regular file"):
        read_bundle(root, with_symlink, BundleLimits(), {})

    fifo = root / "graphify-out" / "pipe.md"
    os.mkfifo(fifo)
    with_fifo = descriptor.artifacts + (SelectedArtifact("article", "graphify-out/pipe.md"),)

    with pytest.raises(ArtifactError, match="not a regular file"):
        read_bundle(root, with_fifo, BundleLimits(), {})


def test_read_bundle_rejects_oversized_artifact_and_bundle(make_bundle):
    root, value = make_bundle(layout="explicit")
    descriptor = load_descriptor(value)

    with pytest.raises(ArtifactError, match="exceeds per-artifact limit"):
        read_bundle(root, descriptor.artifacts, BundleLimits(max_artifact_bytes=16), {})

    with pytest.raises(ArtifactError, match="exceeds bundle limit"):
        read_bundle(root, descriptor.artifacts, BundleLimits(max_total_bytes=64), {})


def test_read_bundle_rejects_file_count_over_limit(make_bundle):
    root, value = make_bundle(layout="explicit")
    descriptor = load_descriptor(value)

    with pytest.raises(ArtifactError, match="exceeds file limit"):
        read_bundle(root, descriptor.artifacts, BundleLimits(max_files=2), {})


def test_read_bundle_hashes_every_artifact(make_bundle):
    root, value = make_bundle(layout="explicit", citation_index=True)
    descriptor = load_descriptor(value)

    retained = read_bundle(root, descriptor.artifacts, BundleLimits(), {})

    assert [(item.role, item.path) for item in retained] == sorted(
        (item.role, item.path) for item in descriptor.artifacts
    )
    for item in retained:
        data = (root / item.path).read_bytes()
        assert item.data == data
        assert item.content_digest == "sha256:" + hashlib.sha256(data).hexdigest()
    graph = next(item for item in retained if item.role == "graph")
    assert json.loads(graph.data)["edges"][0]["relation"] == "calls"


def test_read_bundle_rejects_expected_digest_mismatch(make_bundle):
    root, value = make_bundle(layout="explicit")
    descriptor = load_descriptor(value)
    expected = {"graphify-out/graph.json": "sha256:" + "0" * 64}

    with pytest.raises(ArtifactError, match="digest mismatch"):
        read_bundle(root, descriptor.artifacts, BundleLimits(), expected)
