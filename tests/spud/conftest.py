import json

import pytest


GRAPH_NODES = [
    {
        "id": "orders.submit",
        "label": "orders.submit",
        "source_file": "src/orders.py",
        "source_location": "L4",
        "file_type": "python",
        "_origin": "ast",
    },
    {
        "id": "store.save",
        "label": "store.save",
        "source_file": "src/store.py",
        "source_location": "L1",
        "file_type": "python",
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

OKF_MANIFEST = """repository: repo-a
project: project-a
article_count: 1
generator: spud
"""

RUN_MANIFEST = """run_id: run-1
commit_sha: 1111111111111111111111111111111111111111
uploaded_files: 1
skipped_files: 0
"""

ARTICLE_ROOTS = {"current": "spud-out/markdown", "legacy": "spud-out"}


def graph_index_from_nodes(nodes):
    return [
        {
            "label": node["label"],
            "norm_label": node["label"].lower().replace(" ", ""),
            "source_file": node["source_file"],
            "source_location": node["source_location"],
            "community_name": "",
            "file_type": node["file_type"],
        }
        for node in nodes
    ]


def write_file(bundle_root, relative, text):
    path = bundle_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


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
            write_file(bundle_root, "graphify-out/graph.json", json.dumps(payload, indent=2))
            selected.append({"role": "graph", "path": "graphify-out/graph.json"})
        if report:
            write_file(bundle_root, "graphify-out/GRAPH_REPORT.md", GRAPH_REPORT)
            selected.append({"role": "graph_report", "path": "graphify-out/GRAPH_REPORT.md"})
        if citation_index:
            nodes = GRAPH_NODES if graph_override is None else graph_override.get("nodes", [])
            write_file(
                bundle_root,
                "spud-out/json/analysis/inputs/graph-index.json",
                json.dumps(graph_index_from_nodes(nodes), indent=2),
            )
            selected.append(
                {"role": "citation_index", "path": "spud-out/json/analysis/inputs/graph-index.json"}
            )
        article_root = ARTICLE_ROOTS["legacy" if layout == "legacy" else "current"]
        for article in articles:
            relative = f"{article_root}/{article}"
            write_file(bundle_root, relative, ARTICLE_TEXT)
            selected.append({"role": "article", "path": relative})
        if okf_manifest:
            write_file(bundle_root, "spud-out/manifest.yaml", OKF_MANIFEST)
            selected.append({"role": "okf_manifest", "path": "spud-out/manifest.yaml"})
        if run_manifest:
            write_file(bundle_root, "run-manifest.yaml", RUN_MANIFEST)
            selected.append({"role": "run_manifest", "path": "run-manifest.yaml"})

        descriptor_value = {
            "descriptor_version": "knowitall.spud-admission/v1",
            "project_id": project,
            "repository_id": repository,
            "bundle_id": bundle_id,
            "supplied": dict(supplied or {}),
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
