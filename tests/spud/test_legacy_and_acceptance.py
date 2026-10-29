import socket
import subprocess
import zipfile

import pytest

from knowitall_spud import (
    AdmissionStore,
    ARTIFACT_CONTRACT,
    ArtifactQueryService,
    DescriptorError,
    load_descriptor,
    resolve_artifacts,
    BundleLimits,
)

from conftest import (
    CITATION_INDEX_PATH,
    GRAPH_PATH,
    GRAPH_REPORT_PATH,
    OKF_MANIFEST_PATH,
    RUN_MANIFEST_PATH,
    SOURCE_EVIDENCE_PATH,
    digest_of,
    normalize_bundle_at,
    write_file,
)


def request_for(query, *, bundle_id="bundle-1", request_id="req-1"):
    return {
        "contract": ARTIFACT_CONTRACT,
        "request_id": request_id,
        "project_id": "project-a",
        "repository_id": "repo-a",
        "selector": {"mode": "bundle", "bundle_id": bundle_id},
        "query": query,
    }


def admit(tmp_path, name, bundle):
    store = AdmissionStore(tmp_path / name)
    receipt = store.admit(bundle)
    return ArtifactQueryService(store, page_size=50, continuation_secret=b"acceptance-secret"), receipt


def reasons(response):
    return {item["reason"] for item in response["missing_evidence"]}


def test_legacy_layout_bundle_is_admissible_and_queryable(tmp_path, make_bundle):
    bundle = normalize_bundle_at(
        *make_bundle(layout="legacy", report=False, citation_index=True, articles=("legacy-analysis.md",))
    )
    service, _receipt = admit(tmp_path, "legacy", bundle)

    narrative = service.execute(request_for({"kind": "narrative_search", "text": "persistence boundary"}))
    assert narrative["status"] == "partial"
    assert [record["kind"] for record in narrative["records"]] == ["narrative_passage"]
    assert narrative["records"][0]["locator"]["artifact_path"] == "spud-out/legacy-analysis.md"
    assert reasons(narrative) == {"missing_graph_report"}

    citations = service.execute(request_for({"kind": "artifact_path", "path": CITATION_INDEX_PATH}))
    assert {record["grade"] for record in citations["records"]} == {"recorded_citation"}
    assert all(record["relation"] is None for record in citations["records"])


def test_legacy_layout_without_explicit_selection_surfaces_ambiguity(make_bundle):
    bundle_root, value = make_bundle(layout="auto")
    write_file(bundle_root, "spud-out/legacy-analysis.md", "# Legacy\n\nStale article root.\n")

    with pytest.raises(DescriptorError, match="ambiguous bundle layout"):
        resolve_artifacts(bundle_root, load_descriptor(value), BundleLimits())

    current, _limitations = resolve_artifacts(
        bundle_root, load_descriptor({**value, "layout": "current"}), BundleLimits()
    )
    legacy, _limitations = resolve_artifacts(
        bundle_root, load_descriptor({**value, "layout": "legacy"}), BundleLimits()
    )
    assert [item.path for item in current if item.role == "article"] == [
        "spud-out/markdown/analysis/structural-analysis.md"
    ]
    assert [item.path for item in legacy if item.role == "article"] == ["spud-out/legacy-analysis.md"]


def test_complete_bundle_vertical_slice(tmp_path, make_bundle):
    evidence = {
        "snapshot_id": "snapshot-1",
        "commit": "1" * 40,
        "files": [
            {"path": "src/orders.py", "content_digest": "sha256:" + "2" * 64},
            {"path": "src/store.py", "content_digest": "sha256:" + "3" * 64},
        ],
    }
    bundle_root, value = make_bundle(citation_index=True, source_evidence=evidence)
    value["source_binding"] = {
        "graph_digest": digest_of(bundle_root / GRAPH_PATH),
        "snapshot_id": "snapshot-1",
        "commit_sha": "1" * 40,
        "content_manifest_digest": digest_of(bundle_root / SOURCE_EVIDENCE_PATH),
        "content_manifest_path": SOURCE_EVIDENCE_PATH,
    }
    bundle = normalize_bundle_at(bundle_root, value)
    service, receipt = admit(tmp_path, "complete", bundle)

    response = service.execute(
        request_for({"kind": "relationships", "symbol_id": "orders.submit", "direction": "outgoing", "relations": ["calls"]})
    )

    assert response["status"] == "ok"
    assert response["missing_evidence"] == []
    assert bundle.artifact_completeness == "complete"
    assert response["resolved"] == {
        "bundle_id": "bundle-1",
        "receipt_digest": receipt.receipt_digest,
        "reader_profile": "spud-reader/v1",
        "revision_binding": "bound",
        "bound_snapshot": {
            "snapshot_id": "snapshot-1",
            "commit_sha": "1" * 40,
            "content_manifest_digest": value["source_binding"]["content_manifest_digest"],
        },
    }
    assert response["admission"]["source_coverage"] == "unknown"
    assert {item["role"] for item in response["admission"]["artifacts"]} == {
        "graph",
        "graph_report",
        "citation_index",
        "article",
        "okf_manifest",
        "run_manifest",
        "source_evidence",
    }
    record = response["records"][0]
    assert record["grade"] == "recorded_artifact"
    assert record["attribution"] == {"_origin": "ast", "confidence": "EXTRACTED"}
    assert record["source_reference"]["path"] == "src/orders.py"
    assert record["locator"]["content_digest"] == digest_of(bundle_root / GRAPH_PATH)


def test_partial_bundle_vertical_slice(tmp_path, make_bundle):
    bundle = normalize_bundle_at(
        *make_bundle(report=False, supplied={}, run_manifest={"total_files_skipped": "3"})
    )
    service, _receipt = admit(tmp_path, "partial", bundle)

    response = service.execute(
        request_for({"kind": "relationships", "symbol_id": "orders.submit", "direction": "outgoing", "relations": ["calls"]})
    )

    assert response["status"] == "partial"
    assert response["records"]
    assert reasons(response) == {"missing_graph_report", "unknown_generator_version", "skipped_uploads"}
    assert response["resolved"]["revision_binding"] == "asserted"
    assert response["resolved"]["bound_snapshot"] is None
    assert bundle.artifact_completeness == "partial"
    kinds = {item["reason"]: item["kind"] for item in response["missing_evidence"]}
    assert kinds["missing_graph_report"] == "artifact"
    assert kinds["unknown_generator_version"] == "provenance"


def test_admission_performs_no_subprocess_or_network(monkeypatch, tmp_path, make_bundle):
    def forbidden(*args, **kwargs):
        raise AssertionError("admission must not run subprocesses or open sockets")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    bundle = normalize_bundle_at(*make_bundle(citation_index=True))
    service, _receipt = admit(tmp_path, "sandboxed", bundle)

    for query in (
        {"kind": "symbol", "name": "orders.submit", "match": "exact"},
        {"kind": "artifact_path", "path": GRAPH_PATH},
        {"kind": "narrative_search", "text": "orders"},
    ):
        assert service.execute(request_for(query))["status"] == "ok"


def test_archives_are_not_extracted(tmp_path, make_bundle):
    bundle_root, value = make_bundle(layout="explicit")
    archive_path = "spud-out/site-bundle.zip"
    target = bundle_root / archive_path
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("site/index.html", "<html>escaped payload</html>")
    value["artifacts"].append({"role": "archive", "path": archive_path})

    bundle = normalize_bundle_at(bundle_root, value)

    assert (archive_path, "unsupported_artifact_format") in bundle.limitations
    retained = next(item for item in bundle.artifacts if item.path == archive_path)
    assert retained.data == target.read_bytes()
    assert retained.data[:2] == b"PK"
    assert all(record.locator.artifact_path != archive_path for record in bundle.records)
    assert not any(path.name == "index.html" for path in bundle_root.rglob("*"))

    service, _receipt = admit(tmp_path, "archive", bundle)
    response = service.execute(request_for({"kind": "artifact_path", "path": archive_path}))
    assert response["status"] == "partial"
    assert response["records"] == []
    assert "unsupported_artifact_format" in reasons(response)
