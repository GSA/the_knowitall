import json

import pytest

from knowitall_spud.artifacts import read_bundle
from knowitall_spud.descriptor import BundleLimits, load_descriptor, resolve_artifacts
from knowitall_spud.records import normalize_bundle, read_flat_yaml

from conftest import (
    ARTICLE_TEXT,
    CITATION_INDEX_PATH,
    GRAPH_EDGES,
    GRAPH_NODES,
    GRAPH_PATH,
    GRAPH_REPORT_PATH,
    OKF_MANIFEST_PATH,
    RUN_MANIFEST_PATH,
    SOURCE_EVIDENCE_PATH,
    digest_of,
    write_file,
)


def normalize(bundle_root, descriptor_value):
    descriptor = load_descriptor(descriptor_value)
    limits = BundleLimits()
    selected, limitations = resolve_artifacts(bundle_root, descriptor, limits)
    retained = read_bundle(bundle_root, selected, limits, descriptor.expected_digests)
    return normalize_bundle(descriptor, retained, limitations)


def by_kind(bundle, kind):
    return tuple(record for record in bundle.records if record.kind == kind)


def reasons(bundle, scope=None):
    return {reason for path, reason in bundle.limitations if scope is None or path == scope}


def test_graph_records_are_recorded_artifact_with_attribution(make_bundle):
    bundle = normalize(*make_bundle())

    symbols = by_kind(bundle, "graph_symbol")
    relationships = by_kind(bundle, "graph_relationship")
    assert {record.name for record in symbols} == {"orders.submit", "store.save"}
    assert {record.grade for record in symbols + relationships} == {"recorded_artifact"}
    submit = next(record for record in symbols if record.name == "orders.submit")
    assert submit.attribution["_origin"] == "ast"
    assert submit.locator.pointer == "/nodes/0"
    assert submit.locator.artifact_path == GRAPH_PATH
    assert submit.source_reference.path == "src/orders.py"
    assert (submit.source_reference.start_line, submit.source_reference.end_line) == (4, 5)
    edge = relationships[0]
    assert (edge.subject, edge.relation, edge.object) == ("orders.submit", "calls", "store.save")
    assert edge.attribution["confidence"] == "EXTRACTED"
    assert edge.attribution["_origin"] == "ast"
    assert edge.locator.pointer == "/edges/0"
    assert bundle.reader_profile == "spud-reader/v1"


def test_graph_edge_with_unknown_endpoint_fails_indexing(make_bundle):
    broken = {"nodes": GRAPH_NODES, "edges": [{**GRAPH_EDGES[0], "target": "missing.symbol"}]}
    bundle = normalize(*make_bundle(graph_override=broken))

    assert by_kind(bundle, "graph_symbol") == ()
    assert by_kind(bundle, "graph_relationship") == ()
    assert (GRAPH_PATH, "invalid_graph_records") in bundle.limitations
    assert any(item.path == GRAPH_PATH for item in bundle.artifacts)


def test_duplicate_graph_node_identity_fails_indexing(make_bundle):
    duplicated = {"nodes": [GRAPH_NODES[0], GRAPH_NODES[0]], "edges": []}
    bundle = normalize(*make_bundle(graph_override=duplicated))

    assert by_kind(bundle, "graph_symbol") == ()
    assert (GRAPH_PATH, "invalid_graph_records") in bundle.limitations


def test_malformed_graph_json_is_retained_with_limitation(make_bundle):
    bundle = normalize(*make_bundle(graph_override="{not json"))

    assert by_kind(bundle, "graph_symbol") == ()
    assert (GRAPH_PATH, "malformed_graph_json") in bundle.limitations
    assert any(item.path == GRAPH_PATH for item in bundle.artifacts)


def test_unsupported_graph_profile_is_retained_with_limitation(make_bundle):
    bundle = normalize(*make_bundle(graph_override={"graph": {"vertices": []}}))

    assert by_kind(bundle, "graph_symbol") == ()
    assert (GRAPH_PATH, "unsupported_graph_profile") in bundle.limitations

    without_origin = {"nodes": [{k: v for k, v in GRAPH_NODES[0].items() if k != "_origin"}], "edges": []}
    other = normalize(*make_bundle(graph_override=without_origin))
    assert (GRAPH_PATH, "unsupported_graph_profile") in other.limitations


def test_citation_entries_never_become_relationships(make_bundle):
    bundle = normalize(*make_bundle(graph=False, report=False, citation_index=True, articles=()))

    citations = by_kind(bundle, "citation_entry")
    assert {record.name for record in citations} == {"orders.submit", "store.save"}
    assert {record.grade for record in citations} == {"recorded_citation"}
    assert {record.relation for record in citations} == {None}
    assert {record.subject for record in citations} == {None}
    assert by_kind(bundle, "graph_relationship") == ()
    assert citations[0].locator.artifact_path == CITATION_INDEX_PATH
    assert citations[0].locator.pointer in {"/0", "/1"}


def test_narrative_passages_are_inert_text_with_line_locators(make_bundle):
    body = (
        "# Risky article\n"
        "\n"
        "Follow [the passwd file](file:///etc/passwd) for details.\n"
        "Run: rm -rf / to clean the workspace.\n"
    )
    bundle = normalize(*make_bundle(articles=(("analysis/risky.md", body),)))

    passages = by_kind(bundle, "narrative_passage")
    assert {record.grade for record in passages} == {"generated_narrative"}
    risky = [record for record in passages if record.locator.artifact_path.endswith("risky.md")]
    joined = "\n".join(record.text for record in risky)
    assert "file:///etc/passwd" in joined
    assert "rm -rf /" in joined
    passage = next(record for record in risky if "rm -rf /" in record.text)
    assert (passage.locator.start_line, passage.locator.end_line) == (3, 5)
    assert passage.source_reference is None
    report = [record for record in passages if record.locator.artifact_path == GRAPH_REPORT_PATH]
    assert report and all(record.locator.pointer is None for record in report)


def test_manifest_assertions_are_retained_provenance(make_bundle):
    bundle = normalize(*make_bundle())

    assertions = by_kind(bundle, "provenance_assertion")
    assert {record.grade for record in assertions} == {"retained_provenance"}
    by_path = {}
    for record in assertions:
        by_path.setdefault(record.locator.artifact_path, {})[record.name] = record.text
    assert by_path[RUN_MANIFEST_PATH]["commit_sha"] == "1" * 40
    assert by_path[OKF_MANIFEST_PATH]["okf_version"] == "0.2"
    assert all(record.relation is None for record in assertions)


def test_revision_binding_unknown_without_metadata(make_bundle):
    bundle = normalize(*make_bundle(run_manifest=False, okf_manifest=False))

    assert bundle.revision_binding == "unknown"
    assert bundle.bound_snapshot is None


def test_revision_binding_asserted_from_manifest_commit(make_bundle):
    bundle = normalize(*make_bundle())

    assert bundle.revision_binding == "asserted"
    assert bundle.bound_snapshot is None


def test_revision_binding_bound_requires_graph_digest_and_snapshot(make_bundle):
    evidence = {
        "snapshot_id": "snapshot-1",
        "commit": "1" * 40,
        "files": [
            {"path": "src/orders.py", "content_digest": "sha256:" + "2" * 64},
            {"path": "src/store.py", "content_digest": "sha256:" + "3" * 64},
        ],
    }
    bundle_root, value = make_bundle(source_evidence=evidence)
    binding = {
        "graph_digest": digest_of(bundle_root / GRAPH_PATH),
        "snapshot_id": "snapshot-1",
        "commit_sha": "1" * 40,
        "content_manifest_digest": digest_of(bundle_root / SOURCE_EVIDENCE_PATH),
        "content_manifest_path": SOURCE_EVIDENCE_PATH,
    }
    value["source_binding"] = binding

    bundle = normalize(bundle_root, value)

    assert bundle.revision_binding == "bound"
    assert bundle.bound_snapshot == {
        "snapshot_id": "snapshot-1",
        "commit_sha": "1" * 40,
        "content_manifest_digest": binding["content_manifest_digest"],
    }
    assert "unverified_source_binding" not in reasons(bundle)


def test_revision_binding_rejects_binding_with_wrong_graph_digest(make_bundle):
    evidence = {"snapshot_id": "snapshot-1", "commit": "1" * 40, "files": []}
    bundle_root, value = make_bundle(source_evidence=evidence)
    value["source_binding"] = {
        "graph_digest": "sha256:" + "0" * 64,
        "snapshot_id": "snapshot-1",
        "commit_sha": "1" * 40,
        "content_manifest_digest": digest_of(bundle_root / SOURCE_EVIDENCE_PATH),
        "content_manifest_path": SOURCE_EVIDENCE_PATH,
    }

    bundle = normalize(bundle_root, value)

    assert bundle.revision_binding == "asserted"
    assert bundle.bound_snapshot is None
    assert (GRAPH_PATH, "unverified_source_binding") in bundle.limitations


def test_unknown_generator_version_and_skipped_uploads_are_limitations(make_bundle):
    bundle = normalize(*make_bundle(supplied={}, run_manifest={"total_files_skipped": "2"}))

    assert reasons(bundle) >= {"unknown_generator_version", "skipped_uploads"}
    assert bundle.artifact_completeness == "partial"


def test_artifact_completeness_and_source_coverage(make_bundle):
    complete = normalize(*make_bundle())
    assert (complete.artifact_completeness, complete.source_coverage) == ("complete", "unknown")

    partial = normalize(*make_bundle(report=False))
    assert (partial.artifact_completeness, partial.source_coverage) == ("partial", "unknown")


def test_read_flat_yaml_ignores_unsupported_structures():
    data = (
        "okf_version: \"0.2\"\n"
        "# a comment\n"
        "repository:\n"
        "  url: unknown\n"
        "  commit: deadbeef\n"
        "tags:\n"
        "  - okf\n"
        "  - documentation\n"
        "total: 3\n"
        "nested: {inline: map}\n"
        "broken line without separator\n"
    )

    assert read_flat_yaml(data.encode("utf-8")) == {
        "okf_version": "0.2",
        "tags": "okf, documentation",
        "total": "3",
    }


def test_read_flat_yaml_rejects_undecodable_bytes():
    assert read_flat_yaml(b"\xff\xfe not utf8") == {}


def bound_bundle(make_bundle, *, evidence=None, graph_override=None, binding_extra=None, **kwargs):
    evidence = evidence if evidence is not None else {
        "snapshot_id": "snapshot-1",
        "commit": "1" * 40,
        "files": [
            {"path": "src/orders.py", "content_digest": "sha256:" + "2" * 64},
            {"path": "src/store.py", "content_digest": "sha256:" + "3" * 64},
        ],
    }
    bundle_root, value = make_bundle(source_evidence=evidence, graph_override=graph_override, **kwargs)
    value["source_binding"] = {
        "graph_digest": digest_of(bundle_root / GRAPH_PATH) if (bundle_root / GRAPH_PATH).exists() else "sha256:" + "0" * 64,
        "snapshot_id": "snapshot-1",
        "commit_sha": "1" * 40,
        "content_manifest_digest": digest_of(bundle_root / SOURCE_EVIDENCE_PATH),
        "content_manifest_path": SOURCE_EVIDENCE_PATH,
        **(binding_extra or {}),
    }
    return normalize(bundle_root, value)


def test_binding_is_not_bound_when_the_graph_was_never_parsed(make_bundle):
    bundle = bound_bundle(make_bundle, graph_override="{not json")

    assert bundle.revision_binding == "asserted"
    assert bundle.bound_snapshot is None
    assert (GRAPH_PATH, "unbound_graph_source_files") in bundle.limitations
    assert (GRAPH_PATH, "malformed_graph_json") in bundle.limitations


def test_binding_is_not_bound_when_a_graph_record_has_no_source_file(make_bundle):
    edge = {key: item for key, item in GRAPH_EDGES[0].items() if key != "source_file"}
    bundle = bound_bundle(make_bundle, graph_override={"nodes": GRAPH_NODES, "edges": [edge]})

    assert bundle.revision_binding == "asserted"
    assert (GRAPH_PATH, "unbound_graph_source_files") in bundle.limitations


def test_binding_reports_uncovered_graph_source_files(make_bundle):
    evidence = {"snapshot_id": "snapshot-1", "files": [{"path": "src/orders.py", "content_digest": "sha256:" + "2" * 64}]}
    bundle = bound_bundle(make_bundle, evidence=evidence)

    assert bundle.revision_binding == "asserted"
    assert (GRAPH_PATH, "unbound_graph_source_files") in bundle.limitations


def test_binding_without_a_graph_artifact_reports_missing_bound_graph(make_bundle):
    bundle = bound_bundle(make_bundle, graph=False)

    assert bundle.revision_binding == "asserted"
    assert (GRAPH_PATH, "missing_bound_graph") in bundle.limitations


@pytest.mark.parametrize(
    "evidence",
    [
        {"snapshot_id": "other-snapshot", "files": []},
        {"files": [{"path": "src/orders.py", "content_digest": "sha256:" + "2" * 64}]},
        {"snapshot_id": "snapshot-1", "files": "src/orders.py"},
        {"snapshot_id": "snapshot-1", "files": [{"path": "src/orders.py", "content_digest": "abc"}]},
    ],
)
def test_binding_rejects_unusable_content_manifest_evidence(make_bundle, evidence):
    bundle = bound_bundle(make_bundle, evidence=evidence)

    assert bundle.revision_binding == "asserted"
    assert (GRAPH_PATH, "unverified_source_binding") in bundle.limitations


@pytest.mark.parametrize("supplied_coverage", ["complete", "partial"])
def test_source_coverage_follows_a_verified_binding(make_bundle, supplied_coverage):
    bundle = bound_bundle(make_bundle, binding_extra={"source_coverage": supplied_coverage})

    assert bundle.revision_binding == "bound"
    assert bundle.source_coverage == supplied_coverage


def test_placeholder_commit_metadata_stays_unknown(make_bundle):
    bundle = normalize(*make_bundle(okf_manifest=False, supplied={}, run_manifest={"commit_sha": "unknown"}))

    assert bundle.revision_binding == "unknown"
    assert bundle.bound_snapshot is None


def test_unparsable_or_inverted_source_location_stays_unknown(make_bundle):
    nodes = [
        {**GRAPH_NODES[0], "source_location": "L4-x"},
        {**GRAPH_NODES[1], "source_location": "L10-2"},
    ]
    bundle = normalize(*make_bundle(graph_override={"nodes": nodes, "edges": []}))

    for record in by_kind(bundle, "graph_symbol"):
        assert (record.source_reference.start_line, record.source_reference.end_line) == (None, None)


def test_malformed_and_invalid_citation_index_are_reported(make_bundle):
    bundle_root, value = make_bundle(layout="explicit", citation_index=True)
    (bundle_root / CITATION_INDEX_PATH).write_text("{not json", encoding="utf-8")
    assert (CITATION_INDEX_PATH, "malformed_citation_index") in normalize(bundle_root, value).limitations

    (bundle_root / CITATION_INDEX_PATH).write_text(json.dumps([{"norm_label": "x"}]), encoding="utf-8")
    assert (CITATION_INDEX_PATH, "invalid_citation_records") in normalize(bundle_root, value).limitations

    (bundle_root / CITATION_INDEX_PATH).write_text(json.dumps({"entries": []}), encoding="utf-8")
    assert (CITATION_INDEX_PATH, "unsupported_citation_profile") in normalize(bundle_root, value).limitations


def test_undecodable_narrative_and_unreadable_manifest_are_reported(make_bundle):
    bundle_root, value = make_bundle(layout="explicit")
    (bundle_root / GRAPH_REPORT_PATH).write_bytes(b"# Report\n\n\xff\xfe\n")
    (bundle_root / RUN_MANIFEST_PATH).write_bytes(b"\xff\xfe not utf8")

    bundle = normalize(bundle_root, value)

    assert (GRAPH_REPORT_PATH, "undecodable_narrative_text") in bundle.limitations
    assert (RUN_MANIFEST_PATH, "unreadable_manifest_fields") in bundle.limitations


@pytest.mark.parametrize("commit", ["unknown", "   ", "tbd"])
def test_binding_with_a_placeholder_commit_is_never_bound(make_bundle, commit):
    bundle = bound_bundle(make_bundle, binding_extra={"commit_sha": commit})

    assert bundle.revision_binding != "bound"
    assert bundle.bound_snapshot is None
    assert (GRAPH_PATH, "unverified_source_binding") in bundle.limitations


def test_provenance_assertions_locate_their_manifest_lines(make_bundle):
    bundle_root, value = make_bundle()
    bundle = normalize(bundle_root, value)
    manifest = next(item for item in bundle.artifacts if item.path == RUN_MANIFEST_PATH)
    lines = manifest.data.decode("utf-8").split("\n")

    assertions = [
        record
        for record in bundle.records
        if record.kind == "provenance_assertion" and record.locator.artifact_path == RUN_MANIFEST_PATH
    ]
    assert assertions

    for record in assertions:
        start, end = record.locator.start_line, record.locator.end_line
        assert start is not None and end is not None and end > start
        assert any(line.strip().startswith(f"{record.name}:") for line in lines[start - 1 : end - 1])


def test_binding_requires_commit_evidence_in_the_retained_manifest(make_bundle):
    bundle = bound_bundle(
        make_bundle,
        evidence={
            "snapshot_id": "snapshot-1",
            "files": [
                {"path": "src/orders.py", "content_digest": "sha256:" + "2" * 64},
                {"path": "src/store.py", "content_digest": "sha256:" + "3" * 64},
            ],
        },
    )

    assert bundle.revision_binding == "asserted"
    assert bundle.bound_snapshot is None
    assert (GRAPH_PATH, "unbound_commit_evidence") in bundle.limitations


def test_binding_rejects_commit_evidence_naming_a_different_commit(make_bundle):
    bundle = bound_bundle(
        make_bundle,
        evidence={
            "snapshot_id": "snapshot-1",
            "commit": "9" * 40,
            "files": [
                {"path": "src/orders.py", "content_digest": "sha256:" + "2" * 64},
                {"path": "src/store.py", "content_digest": "sha256:" + "3" * 64},
            ],
        },
    )

    assert bundle.revision_binding == "asserted"
    assert bundle.bound_snapshot is None
    assert (GRAPH_PATH, "unbound_commit_evidence") in bundle.limitations


def test_binding_is_bound_when_commit_evidence_agrees(make_bundle):
    bundle = bound_bundle(
        make_bundle,
        evidence={
            "snapshot_id": "snapshot-1",
            "commit": "1" * 40,
            "files": [
                {"path": "src/orders.py", "content_digest": "sha256:" + "2" * 64},
                {"path": "src/store.py", "content_digest": "sha256:" + "3" * 64},
            ],
        },
    )

    assert bundle.revision_binding == "bound"
    assert bundle.bound_snapshot["commit_sha"] == "1" * 40


def test_read_flat_yaml_preserves_hash_characters_inside_quoted_scalars():
    data = (
        'title: "Release #42"\n'
        "ticket: 'bug #7 fixed'\n"
        "bare: value # trailing comment\n"
        'unterminated: "open #value\n'
        "tags:\n"
        "  - 'tag #1'\n"
        "  - plain # comment\n"
    )

    assert read_flat_yaml(data.encode("utf-8")) == {
        "title": "Release #42",
        "ticket": "bug #7 fixed",
        "bare": "value",
        "tags": "tag #1, plain",
    }


def test_read_flat_yaml_skips_double_quoted_scalars_it_cannot_represent():
    data = (
        'title: "Release\\nnotes"\n'
        'quoted: "say \\"hello\\""\n'
        "plain: kept\n"
    )

    assert read_flat_yaml(data.encode("utf-8")) == {"plain": "kept"}


@pytest.mark.parametrize("named", ["graphify-out/graph.json", "graphify-out/graph-extra.json"])
def test_binding_is_not_bound_when_a_second_graph_was_never_verified(make_bundle, named):
    bundle_root, value = make_bundle(layout="explicit")
    second = "graphify-out/graph-extra.json"
    write_file(bundle_root, second, json.dumps({"nodes": GRAPH_NODES, "edges": []}, indent=2))
    value["artifacts"] = list(value["artifacts"]) + [{"role": "graph", "path": second}]
    write_file(
        bundle_root,
        SOURCE_EVIDENCE_PATH,
        json.dumps(
            {
                "snapshot_id": "snapshot-1",
                "commit": "1" * 40,
                "files": [
                    {"path": "src/orders.py", "content_digest": "sha256:" + "2" * 64},
                    {"path": "src/store.py", "content_digest": "sha256:" + "3" * 64},
                ],
            }
        ),
    )
    value["artifacts"].append({"role": "source_evidence", "path": SOURCE_EVIDENCE_PATH})
    value["source_binding"] = {
        "graph_digest": digest_of(bundle_root / named),
        "snapshot_id": "snapshot-1",
        "commit_sha": "1" * 40,
        "content_manifest_digest": digest_of(bundle_root / SOURCE_EVIDENCE_PATH),
        "content_manifest_path": SOURCE_EVIDENCE_PATH,
    }

    bundle = normalize(bundle_root, value)

    assert bundle.revision_binding == "asserted"
    assert bundle.bound_snapshot is None
    assert (GRAPH_PATH, "ambiguous_bound_graph") in bundle.limitations


@pytest.mark.parametrize("supplied_coverage", [["complete"], {"value": "complete"}, 1, None])
def test_unusable_supplied_coverage_stays_unknown(make_bundle, supplied_coverage):
    bundle = bound_bundle(make_bundle, binding_extra={"source_coverage": supplied_coverage})

    assert bundle.revision_binding == "bound"
    assert bundle.source_coverage == "unknown"


def test_read_flat_yaml_skips_multiline_plain_scalars():
    data = b"title: Release\n  notes\ncommit: unknown\n  1111\nplain: kept\n"

    assert read_flat_yaml(data) == {"plain": "kept"}


def test_a_multiline_commit_scalar_is_not_an_asserted_commit(make_bundle):
    bundle = normalize(*make_bundle(run_manifest={"commit_sha": "aaaa\n  bbbb"}))

    assert bundle.revision_binding == "unknown"


def test_an_unverified_binding_assertion_is_retained_as_supplied_provenance(make_bundle):
    binding = {"commit_sha": "4" * 40, "graph_digest": "sha256:" + "0" * 64}
    bundle_root, value = make_bundle(supplied={"generator_version": "spud c80837a"})
    value["source_binding"] = binding

    bundle = normalize(bundle_root, value)

    assert (GRAPH_PATH, "unverified_source_binding") in bundle.limitations
    assert bundle.revision_binding == "asserted"
    assert bundle.bound_snapshot is None
    # The unverified assertion stays visible, so a later reader can see which
    # commit the caller claimed and that nothing verified it.
    assert bundle.supplied_binding == binding
    binding["commit_sha"] = "5" * 40
    assert bundle.supplied_binding["commit_sha"] == "4" * 40


def test_two_differing_unverified_binding_assertions_do_not_normalize_alike(make_bundle):
    first_root, first = make_bundle(supplied={"generator_version": "spud c80837a"})
    second_root, second = make_bundle(supplied={"generator_version": "spud c80837a"})
    first["source_binding"] = {"commit_sha": "4" * 40, "graph_digest": "sha256:" + "0" * 64}
    second["source_binding"] = {"commit_sha": "5" * 40, "graph_digest": "sha256:" + "0" * 64}

    assert normalize(first_root, first) != normalize(second_root, second)
