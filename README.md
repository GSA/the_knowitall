# The Knowitall

> **Status: untested on real code.** So far it has only been tested on
> synthetic Python and TypeScript fixtures.
>
> **Known blocker (Kata `88nk`):** real repositories currently fail during
> extraction. When code references something outside the repository, such as
> `ValueError`, Graphify adds a placeholder node with no source file. The
> Knowitall then rejects the whole graph with `native node is not deterministic
> admitted-source evidence`. Fix this before ingesting real code.

The Knowitall builds a code knowledge graph for a specific Git commit and answers
questions about that code. Agents use it to look up code facts: where a symbol
is defined, what it calls or imports, which symbols are in a file, and what a
line range contains. Every answer names the snapshot and commit it came from,
and states how complete the coverage is.

GitHub: `GSA/the_knowitall`. Local checkout: `~/the_knowitall`. Kata project: `the_knowitall`.

**Intended use:** **The Engineer** (`~/kenn-kopy`) and its Pi or Forge agents
query The Knowitall for code context while they work on tasks. Business rules and
documents belong in **The Librarian**.

## How it works

1. **Snapshot:** copy a Git repository (from a URL or local path) at an exact commit.
2. **Extract:** run pinned Graphify `0.9.96` offline over the snapshot. Later
   runs update the graph incrementally, and interrupted runs can be resumed.
3. **Publish:** validate the graph and publish it to a local store.
4. **Query:** answer `knowitall.code-context/v1` JSON requests (`symbol`,
   `dependencies`, `path`, `source_range`).

This is a Python library. It has no CLI, network service, or MCP server yet.

## Setup

Requirements: Linux x86_64, Python 3.12+ for the library, Python 3.14 for the
Graphify runtime, and `python3-venv`. The wheel-build test needs `ensurepip`.

```sh
cd ~/the_knowitall
python3 -m venv --without-pip .venv
python3 -m pip --python .venv/bin/python install -e '.[test]'

# Graphify runtime. Packages are installed from requirements/graphify.lock and hash-checked.
python3.14 -m venv --without-pip .local/graphify-venv
python3 -m pip --python .local/graphify-venv/bin/python install \
  --require-hashes --no-deps -r requirements/graphify.lock
export KNOWITALL_GRAPHIFY_RUNTIME="$PWD/.local/graphify-venv"

# Verify the setup.
.venv/bin/python scripts/check-contract-examples.py
.venv/bin/python -m pytest -q
```

If `KNOWITALL_GRAPHIFY_RUNTIME` is unset, the tests that run real Graphify are
skipped.

## Adding a repository (building the graph)

Give The Knowitall a repository URL (`https://` or `ssh://`) or a local Git path.
Put the following script in `.local/ingest.py`. Git ignores `.local/`.

```python
import os, sys
from pathlib import Path
from knowitall_snapshot import SnapshotPolicy, checkout_remote, create_snapshot
from knowitall_graphify import GraphifyConfig, executable_digest
from knowitall_publication import PublicationStore
from knowitall_updates import UpdateLedger, UpdateRunner

origin, project_id, repo_id = sys.argv[1:4]
state = Path(".local").resolve()
runtime = Path(os.environ["KNOWITALL_GRAPHIFY_RUNTIME"])
python = runtime / "bin/python"
config = GraphifyConfig(executable=python, python_path=str(runtime / "lib/python3.14/site-packages"),
                        expected_executable_digest=executable_digest(python))

checkout = checkout_remote(origin, state / "repos" / repo_id)
snapshot = create_snapshot(checkout.path, project_id, repo_id, state / "snapshots", SnapshotPolicy(), origin=checkout.origin)
store = PublicationStore(state / "publication")
ledger = UpdateLedger(state / "updates", store)
runner = UpdateRunner(ledger, config)
request_id = f"{repo_id}-{snapshot.snapshot_id}"
if not ledger.request_path(request_id).exists():
    try:
        current = store.resolve_current(project_id, repo_id)
    except KeyError:
        current = None
    runner.submit(request_id, snapshot, expected_current=current)
status = runner.resume(request_id)
print(status.phase, status.reasons or "", f"snapshot={snapshot.snapshot_id}")
```

```sh
.venv/bin/python .local/ingest.py https://github.com/ORG/REPO.git my-project my-repo
```

- **Credentials:** URLs with embedded credentials are rejected, and Git
  credential helpers are disabled. The script can clone public repos and local
  paths. For a private repo, clone it yourself first and pass the local path.
- **Refresh:** re-run the script. It fetches the latest commit and updates the
  graph incrementally. The earlier graph stays available.
- **Resume:** if a run is interrupted, re-run the same command. The run's
  progress is saved in `.local/updates`.
- **Commits:** only committed content is indexed. A checkout with uncommitted
  changes is rejected.

## Connecting consumer agents

There is **no MCP server yet** (Kata `vz6q`). Until it exists, agents connect
through a local stdio process. The process reads one JSON request per line and
writes one JSON response per line. Put the following script in `.local/serve.py`:

```python
import sys
from pathlib import Path
from knowitall_publication import PublicationStore
from knowitall_query import QueryService, serve_stdio

serve_stdio(QueryService(PublicationStore(Path(".local/publication").resolve())), sys.stdin, sys.stdout)
```

```sh
echo '{"contract":"knowitall.code-context/v1","request_id":"1","project_id":"my-project",
"repository_id":"my-repo","selector":{"mode":"current"},
"query":{"kind":"symbol","name":"submit_order()","match":"exact"}}' | tr -d '\n' \
  | .venv/bin/python .local/serve.py
```

Request and response formats are defined in
[`schemas/knowitall.code-context/v1/`](schemas/knowitall.code-context/v1/), with
examples in [`examples/`](examples/knowitall.code-context/v1/). Graphify writes
function names with `()`. Statuses such as `partial`, `stale`, or `not_found`
and the `missing_evidence` field are part of the answer, so agents must not
discard them.

When an MCP adapter exists, it will wrap the same request and response format.
Agents will then register it in Pi's `mcp.json` with the same pattern as
The Librarian.

## Importing SPUD artifacts (optional)

`knowitall_spud` admits an already produced SPUD bundle (`graph.json`, reports,
OKF/run manifests, citation indexes) as graded, queryable evidence under its own
`knowitall.spud-artifacts/v1` contract. It does not adopt SPUD's pipeline: it
only reads retained files, and never runs SPUD or Graphify, extracts an archive,
opens a socket or subprocess, or executes anything from a bundle.

```python
import json
from pathlib import Path
from knowitall_spud import (
    AdmissionStore, ArtifactQueryService, BundleLimits,
    load_descriptor, normalize_bundle, read_bundle, resolve_artifacts,
)

root = Path(".local/spud-bundle").resolve()
descriptor = load_descriptor(json.loads((root / "admission.json").read_text(encoding="utf-8")))
limits = BundleLimits()
selected, limitations = resolve_artifacts(root, descriptor, limits)
retained = read_bundle(root, selected, limits, descriptor.expected_digests)

store = AdmissionStore(Path(".local/spud-admission").resolve())
receipt = store.admit(normalize_bundle(descriptor, retained, limitations))
response = ArtifactQueryService(store).execute(request)
```

Each answer names the bundle, its receipt digest and the pinned `spud-reader/v1`
profile, and states a revision binding of `unknown`, `asserted` or `bound`.
Missing companions, unknown producer versions, skipped uploads, unverified
commit metadata and incomplete source scope stay explicit limitations, so an
admitted bundle never claims SPUD ran locally, that the bundle is current, or
that source coverage was complete. Request and response formats live in
[`schemas/knowitall.spud-artifacts/v1/`](schemas/knowitall.spud-artifacts/v1/)
with examples in [`examples/`](examples/knowitall.spud-artifacts/v1/); see
[docs/spud-artifact-admission.md](docs/spud-artifact-admission.md) for the
descriptor format, layouts, evidence grades and limitation reasons.

## Rules

- Keep cloned repos, snapshots, and graphs under `.local/`. Never commit them.
- Treat ingested code as untrusted. The pipeline never runs hooks, builds, or
  network calls while extracting.
- Track work in Kata (`kata ready --agent`). roborev hooks review every 5 commits.

## Open work

| Kata | Priority | Scope |
| --- | --- | --- |
| `88nk` | `P1` | Handling of unresolved references (**blocks real repos**) |
| `vz6q` | `P1` | MCP server for consumer agents |
| `3p2d` | `P1` | Isolated MVP instance intake and publication across mirrored Falcon repos |
| `d2qt` | `P3` | Runtime integrity attestation |

More detail: [docs/local-provider.md](docs/local-provider.md) and
[docs/graphify-dependency.md](docs/graphify-dependency.md).
