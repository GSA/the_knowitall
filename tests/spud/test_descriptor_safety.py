import hashlib
import json
import os
import shutil

import pytest

from knowitall_spud.artifacts import ArtifactError, read_bundle, read_regular_file, safe_relative_path
from knowitall_spud.descriptor import (
    BundleLimits,
    DescriptorError,
    SelectedArtifact,
    load_descriptor,
    resolve_artifacts,
)

from conftest import GRAPH_PATH



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


def test_read_regular_file_rejects_entry_swapped_after_the_check(monkeypatch, tmp_path):
    target = tmp_path / "graph.json"
    target.write_bytes(b"x" * 16)
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"y" * 16)
    real_open = os.open

    def swapping(path, flags, *args, **kwargs):
        if str(path).endswith("graph.json"):
            target.unlink()
            target.symlink_to(outside)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swapping)

    with pytest.raises(ArtifactError, match="not a regular file"):
        read_regular_file(tmp_path, "graph.json", 1024)


def test_read_regular_file_caps_the_read_itself(tmp_path):
    (tmp_path / "graph.json").write_bytes(b"x" * 64)

    with pytest.raises(ArtifactError, match="per-artifact limit"):
        read_regular_file(tmp_path, "graph.json", 8)


def test_read_bundle_rejects_unsatisfied_expected_digest(make_bundle):
    root, value = make_bundle(layout="explicit")
    descriptor = load_descriptor(value)
    expected = {"graphify-out/renamed-graph.json": "sha256:" + "0" * 64}

    with pytest.raises(ArtifactError, match="was not selected"):
        read_bundle(root, descriptor.artifacts, BundleLimits(), expected)


def test_resolve_artifacts_ignores_a_symlinked_intermediate_directory(tmp_path, make_bundle):
    root, value = make_bundle(layout="current")
    outside = tmp_path / "outside"
    (outside / "markdown").mkdir(parents=True)
    (outside / "markdown" / "leaked.md").write_text("# Leaked\n", encoding="utf-8")
    (outside / "manifest.yaml").write_text("okf_version: \"0.2\"\n", encoding="utf-8")
    shutil.rmtree(root / "spud-out")
    (root / "spud-out").symlink_to(outside, target_is_directory=True)

    selected, limitations = resolve_artifacts(root, load_descriptor(value), BundleLimits())

    assert [item.path for item in selected if item.role == "article"] == []
    assert all("leaked.md" not in item.path for item in selected)
    assert all(item.role != "okf_manifest" for item in selected)
    assert ("spud-out", "no_articles_selected") in limitations
    assert ("spud-out/manifest.yaml", "missing_okf_manifest") in limitations


def test_resolve_artifacts_skips_symlinked_article_files(make_bundle):
    root, value = make_bundle(layout="current")
    link = root / "spud-out" / "markdown" / "linked.md"
    link.symlink_to(root / "graphify-out" / "GRAPH_REPORT.md")

    selected, _limitations = resolve_artifacts(root, load_descriptor(value), BundleLimits())

    assert [item.path for item in selected if item.role == "article"] == [
        "spud-out/markdown/analysis/structural-analysis.md"
    ]


@pytest.mark.parametrize("identity", ["project_id", "repository_id", "bundle_id"])
def test_load_descriptor_rejects_control_characters_in_identities(make_bundle, identity):
    _root, value = make_bundle()
    value[identity] = "bundle\x001"

    with pytest.raises(DescriptorError, match="control characters"):
        load_descriptor(value)


def test_load_descriptor_strips_surrounding_whitespace_from_identities(make_bundle):
    _root, value = make_bundle()
    value["bundle_id"] = "  bundle-1\t"

    assert load_descriptor(value).bundle_id == "bundle-1"


def test_load_descriptor_reports_non_string_keys_as_descriptor_errors(make_bundle):
    _root, value = make_bundle()
    value[1] = "x"
    value["zz"] = "y"

    with pytest.raises(DescriptorError, match="unsupported keys"):
        load_descriptor(value)


def test_explicit_selection_rejects_duplicate_paths_and_unknown_entry_keys(make_bundle):
    _root, value = make_bundle(layout="explicit")
    duplicated = list(value["artifacts"]) + [dict(value["artifacts"][0])]
    value["artifacts"] = duplicated

    with pytest.raises(DescriptorError, match="selects .* more than once"):
        load_descriptor(value)

    value["artifacts"] = [{"role": "graph", "path": GRAPH_PATH, "note": "extra"}]
    with pytest.raises(DescriptorError, match="unsupported keys"):
        load_descriptor(value)


def test_source_binding_is_copied_defensively(make_bundle):
    _root, value = make_bundle()
    nested = {"files": ["src/orders.py"]}
    value["source_binding"] = {"commit_sha": "1" * 40, "evidence": nested}

    descriptor = load_descriptor(value)
    nested["files"].append("src/injected.py")

    assert descriptor.source_binding == {"commit_sha": "1" * 40, "evidence": {"files": ["src/orders.py"]}}


@pytest.mark.parametrize("entry", [{"scope": "   ", "reason": "missing_article"}, ("\t", "missing_archive")])
def test_declared_missing_rejects_blank_scopes(make_bundle, entry):
    _bundle_root, value = make_bundle()
    value["declared_missing"] = [entry]

    with pytest.raises(DescriptorError, match="nonempty strings"):
        load_descriptor(value)
