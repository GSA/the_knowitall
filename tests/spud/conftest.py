import hashlib
import json

import pytest

from knowitall_spud.artifacts import read_bundle
from knowitall_spud.descriptor import BundleLimits, load_descriptor, resolve_artifacts
from knowitall_spud.records import normalize_bundle
from knowitall_spud.store import AdmissionStore


GRAPH_NODES = [
    {
        "id": "orders.submit",
        "label": "orders.submit",
        "source_file": "src/orders.py",
        "source_location": "L4",
        "file_type": "python",
        "community_name": "orders",
        "_origin": "ast",
    },
    {
        "id": "store.save",
        "label": "store.save",
        "source_file": "src/store.py",
        "source_location": "L1",
        "file_type": "python",
        "community_name": "storage",
        "_origin": "ast",
    },
]

GRAPH_EDGES = [
    {
        "source": "orders.submit",
        "target": "store.save",
        "relation": "calls",
        "confidence": "EXTRACTED",
        "source_file": "src/orders.py",
        "source_location": "L5",
        "_origin": "ast",
    },
]

GRAPH_REPORT = """# Graph report

The orders service submits an order and persists it through the store layer.
Generated narrative text is retained verbatim, never rendered or executed.
"""

ARTICLE_TEXT = """# Structural analysis

`orders.submit` calls `store.save` on every accepted order.
See [the store module](src/store.py) for the persistence boundary.
"""

OKF_MANIFEST = """okf_version: "0.2"
name: repo-a-knowledge
title: OKF Knowledge Bundle for repo-a
repository:
  url: unknown
  commit: unknown
  branch: unknown
stats:
  total_concepts: 1
  domains:
    - analysis
tags:
  - okf
  - documentation
"""

RUN_MANIFEST_FIELDS = {
    "run_id": "run-1",
    "commit_sha": "1111111111111111111111111111111111111111",
    "total_files_uploaded": "1",
    "total_files_skipped": "0",
}

SUPPLIED_METADATA = {
    "generator_version": "spud c80837a825cd412699f0431ad368e14b85ec246b",
    "run_id": "run-1",
}

GRAPH_PATH = "graphify-out/graph.json"
GRAPH_REPORT_PATH = "graphify-out/GRAPH_REPORT.md"
CITATION_INDEX_PATH = "spud-out/json/analysis/inputs/graph-index.json"
OKF_MANIFEST_PATH = "spud-out/manifest.yaml"
RUN_MANIFEST_PATH = "run-manifest.yaml"
SOURCE_EVIDENCE_PATH = "source-evidence/content-manifest.json"

ARTICLE_ROOTS = {"current": "spud-out/markdown", "legacy": "spud-out"}


def digest_of(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def graph_index_from_nodes(nodes):
    return [
        {
            "label": node["label"],
            "norm_label": node["label"].lower().replace(" ", ""),
            "source_file": node["source_file"],
            "source_location": node["source_location"],
            "community_name": node.get("community_name", ""),
            "file_type": node["file_type"],
        }
        for node in nodes
    ]


def flat_yaml(fields):
    return "".join(f"{key}: {value}\n" for key, value in fields.items())


def write_file(bundle_root, relative, text):
    path = bundle_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def normalize_bundle_at(bundle_root, descriptor_value, limits=None):
    """Run the full descriptor -> selection -> retention -> normalization path."""
    descriptor = load_descriptor(descriptor_value)
    limits = limits or BundleLimits()
    selected, limitations = resolve_artifacts(bundle_root, descriptor, limits)
    retained = read_bundle(bundle_root, selected, limits, descriptor.expected_digests)
    return normalize_bundle(descriptor, retained, limitations)


@pytest.fixture
def make_bundle(tmp_path):
    """Write a synthetic SPUD bundle and return (bundle_root, descriptor_value)."""

    counter = 0

    def make(
        *,
        layout="current",
        graph=True,
        report=True,
        citation_index=False,
        articles=("analysis/structural-analysis.md",),
        okf_manifest=True,
        run_manifest=True,
        source_evidence=None,
        supplied=None,
        source_binding=None,
        graph_override=None,
        bundle_id="bundle-1",
        project="project-a",
        repository="repo-a",
    ):
        nonlocal counter
        counter += 1
        bundle_root = tmp_path / f"bundle-{counter}"
        bundle_root.mkdir()
        selected = []

        if graph:
            payload = graph_override
            if payload is None:
                payload = {"nodes": GRAPH_NODES, "edges": GRAPH_EDGES}
            text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
            write_file(bundle_root, GRAPH_PATH, text)
            selected.append({"role": "graph", "path": GRAPH_PATH})
        if report:
            write_file(bundle_root, GRAPH_REPORT_PATH, GRAPH_REPORT)
            selected.append({"role": "graph_report", "path": GRAPH_REPORT_PATH})
        if citation_index:
            nodes = GRAPH_NODES
            if isinstance(graph_override, dict):
                nodes = graph_override.get("nodes", [])
            write_file(bundle_root, CITATION_INDEX_PATH, json.dumps(graph_index_from_nodes(nodes), indent=2))
            selected.append({"role": "citation_index", "path": CITATION_INDEX_PATH})
        article_root = ARTICLE_ROOTS["legacy" if layout == "legacy" else "current"]
        for article in articles:
            name, body = article if isinstance(article, tuple) else (article, ARTICLE_TEXT)
            relative = f"{article_root}/{name}"
            write_file(bundle_root, relative, body)
            selected.append({"role": "article", "path": relative})
        if okf_manifest:
            write_file(bundle_root, OKF_MANIFEST_PATH, OKF_MANIFEST)
            selected.append({"role": "okf_manifest", "path": OKF_MANIFEST_PATH})
        if run_manifest:
            fields = dict(RUN_MANIFEST_FIELDS)
            if isinstance(run_manifest, dict):
                fields.update(run_manifest)
            write_file(bundle_root, RUN_MANIFEST_PATH, flat_yaml(fields))
            selected.append({"role": "run_manifest", "path": RUN_MANIFEST_PATH})
        if source_evidence is not None:
            write_file(bundle_root, SOURCE_EVIDENCE_PATH, json.dumps(source_evidence, indent=2))
            selected.append({"role": "source_evidence", "path": SOURCE_EVIDENCE_PATH})

        descriptor_value = {
            "descriptor_version": "knowitall.spud-admission/v1",
            "project_id": project,
            "repository_id": repository,
            "bundle_id": bundle_id,
            "supplied": dict(SUPPLIED_METADATA if supplied is None else supplied),
            "expected_digests": {},
            "declared_missing": [],
        }
        if source_binding is not None:
            descriptor_value["source_binding"] = source_binding
        if layout == "explicit":
            descriptor_value["layout"] = "explicit"
            descriptor_value["artifacts"] = selected
        elif layout != "auto":
            descriptor_value["layout"] = layout
        return bundle_root, descriptor_value

    return make


@pytest.fixture
def admitted_bundle(tmp_path, make_bundle):
    """Admit a synthetic bundle and return (store, normalized bundle, receipt)."""

    default_store = AdmissionStore(tmp_path / "admissions")

    def make(*, store=None, admit=True, failpoint=None, limits=None, **kwargs):
        target = default_store if store is None else store
        bundle = normalize_bundle_at(*make_bundle(**kwargs), limits=limits)
        receipt = target.admit(bundle, failpoint=failpoint) if admit else None
        return target, bundle, receipt

    return make
