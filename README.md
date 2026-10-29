# The Knowitall

Code context and revision-bound repository knowledge graphs for engineering.

**Status: contract defined with a local synthetic slice, October 28, 2026.** Public repository:
https://github.com/GSA/the_knowitall, tracked locally under Kata project
`the_knowitall` (`.kata.toml`).

## Product boundaries

| Product | Responsibility |
| --- | --- |
| **The Knowitall** | Authorized repository intake, immutable source snapshots, code graph production, technical provenance, and revision/coverage-aware queries |
| **The Librarian** | Business-source intake, originals/renditions, entities/claims, evidence-backed relationships, qualification, corrections, and retrieval |
| **The Engineer** | Kata issues, Forge workspaces/agents/PRs, roborev review, AgentsView visibility, selective agent-event memory, and consumption of both context providers |
| **SPUD** | Independently maintained documentation and analysis product |

Routing follows purpose: technical repository context lives in Knowitall, while
business rules and institutional knowledge live in Librarian with shared source
and version references.

## Findings from the SPUD & Graphify evaluation

Evaluated baselines: SPUD `c80837a`, SPUD Web `8e9626d`, Graphify `0.9.96`
(`dac063456bc1f5d92354ec3936fd9dd1513a83f3`), Confluence exporter `v0.2.4`
(`b310442e22b9501c2527fa344ef272185e427e50`), and Jira exporter `v0.3.4`
(`7894cba1de887452667d1e54594df13f878e1686`).

- **Graphify** provides typed graphs, source locators, deterministic AST/code extraction, incremental updates/deletions, and query/MCP operations.
- **Jira and Confluence exporters** are standalone packages that output raw JSON, Markdown, and attachments directly.
- **Ingestion durability requirements:** per-document/page/attachment completion tracking, watermark advancement only after complete export, and explicit error propagation for attachment and persistence failures.

## Reuse and integration plan

| Capability | Approach |
| --- | --- |
| Graphify parsing and graph queries | Pinned dependency wrapped in Knowitall's snapshot and evidence contract |
| Repository acquisition and graph publication | Knowitall implementation using Git and Graphify incremental extraction |
| Existing SPUD graph/technical outputs | Optional Knowitall admission adapter recording revision and coverage |
| Jira/Confluence export and reconciliation | Librarian adapters over standalone exporters with durable retry and reconciliation |
| Docling extraction | Librarian's existing offline Docling lifecycle plus qualified-retrieval admission |
| OKF metadata/rendition conventions | Supported in Librarian's receiving contract where identity and evidence are preserved |
| Drive and manual file upload | Librarian source adapters feeding the retained-original and receipt lifecycle |

## Repository ingestion and graph building

```text
approved local checkout / read-only remote
  -> resolve exact commit revision and source scope
  -> retain immutable snapshot + content/coverage manifest
  -> pinned deterministic Graphify extraction
  -> validate graph, provenance, and coverage
  -> atomically publish a queryable snapshot
```

1. **Snapshot identity:** Resolve branches/tags to an exact commit SHA and record a manifest binding project/repository identity, origin, commit SHA, content digest, included/excluded/failed paths, extractor/config versions, and artifact hashes.
2. **Submodules and LFS:** Apply explicit submodule and LFS policies with completeness accounting.
3. **Publication lifecycle:** Keep `complete`, `partial`, `blocked`, and `failed` states distinct; stage and validate new graphs before atomic publication while retaining the last known good snapshot.
4. **Query contract:** Return symbols, relationships, and source ranges with snapshot identity, coverage, ambiguity, and freshness metadata.

## Librarian business knowledge & cross-product links

Librarian models capabilities, requirements/business rules, processes, domain
concepts/data definitions, roles, systems/integrations, and decisions using
stable project-scoped IDs, source passage locators/versions, temporal
applicability, evidentiary basis, and review/correction state.

Cross-product associations (`librarian#923h`) link a Librarian assertion to a
Knowitall `repository/snapshot/symbol` identity with explicit evidence,
disposition, and reassessment when either the business source or code revision
changes.

## Shared document intake pipeline (Librarian)

```text
discover or submit -> private staging -> retain/register original
  -> format-routed normalization -> quality/knowledge processing
  -> policy qualification -> selected retrieval publication
```

## Delivery backlog (`kata list --project knowitall`)

Provider design is tracked under `knowitall#vky6` with implementation slices:

| Kata | Scope |
| --- | --- |
| `knowitall#7gv8` | Repository intake and immutable snapshots |
| `knowitall#r9gz` | Pinned Graphify integration |
| `knowitall#8jvw` | Revision-bound queries and evidence packets |
| `knowitall#regc` | Resumable updates and atomic publication |
| `knowitall#axsf` | Optional SPUD technical-artifact admission |

Connected Librarian and Engineer slices (`engi-platform#pyzt`):

| Kata | Scope |
| --- | --- |
| `librarian#zqdh` | Qualified retrieval of selected Docling renditions |
| `librarian#1md4` | Durable intake stages, DLQ, and replay |
| `librarian#rst9` | Retained-export importer (`librarian#55nx` receiving design) |
| `librarian#bj17` / `5bc5` | Confluence / Jira exporter integration and reconciliation |
| `librarian#3sx1` / `9hqs` | Drive discovery and manual/local-drop intake |
| `librarian#8a5h` / `0nj8` | UTF-8 normalization and standing-policy qualification |
| `librarian#rjr5` | Contribution/disposition transport |
| `librarian#pwhw` -> `xzkj` | Business entity/relationship contract -> first slice |
| `engi-platform#ca6n` -> `hk33` | Shared synthetic fixtures -> end-to-end 3-product demo harness |
| `engi-platform#k4mp` | Task-bound Librarian + Knowitall evidence composition |
| `engi-platform#zbww` -> `pbqn` | Memory value benchmark -> conditional memory integration |

Target end-to-end demonstration (`engi-platform#hk33`):
`source passage -> business rule/entity -> evidence-linked code symbol -> affected dependency -> Engineer change/review`, including interrupted-run recovery and source-update reassessment in isolated temporary fixture stores.

## Provider Contract (`knowitall.code-context/v1`)

`knowitall.code-context/v1` defines the engine-neutral provider/consumer boundary:

| Path | Contents |
| --- | --- |
| `schemas/knowitall.code-context/v1/` | JSON Schemas for the snapshot manifest, query request, query response, and shared definitions |
| `examples/knowitall.code-context/v1/` | Schema-valid manifest, exact request, success response, and partial response |
| `src/knowitall_contract/` | Typed records and validation APIs loaded via `importlib.resources` |

Every response binds project, repository, snapshot, commit (or admitted dirty-content) identity, graph generation, and raw-artifact digest (`current` is accepted only as a request selector). Queries support `symbol`, `dependencies`, `path`, and `source_range` with explicit status (`ok`, `partial`, `not_found`, `ambiguous`, `stale`, `unavailable`, `invalid_request`), machine-readable missing-evidence records, and cursor-based continuations.

## Local Provider Usage

Extraction uses `graphifyy==0.9.96` pinned by hash (see [`docs/graphify-dependency.md`](docs/graphify-dependency.md) and [`docs/local-provider.md`](docs/local-provider.md)).

```sh
export PYTHONPATH="/absolute/path/to/test-dependencies:$PWD/src"
export KNOWITALL_GRAPHIFY_RUNTIME="/absolute/path/to/pinned-graphify-venv"
python3 scripts/check-contract-examples.py
python3 -m pytest -q
```


## Resumable local updates

`knowitall_updates.UpdateLedger` durably captures admitted snapshot bytes and
request/runtime identities before acknowledgment. `UpdateRunner.submit` and
`resume` use Graphify's pinned incremental engine and validated graph/manifest
checkpoints, then publish only against the explicitly saved predecessor.
`inspect` exposes progress and failure reasons; retrying a published request
returns its original receipt without rolling newer `current` evidence backward.
See [the local API and recovery example](docs/local-provider.md#resumable-updates).

Operations are serialized on one local POSIX store; keep one ledger per store.
Incomplete inventories block rather than delete unknown survivors. Valid partial
graphs remain queryable with their actual revision and limitations. The private
ledger retains source bytes and graph companions, so keep it outside Git and
apply an explicit retention policy. No scheduler or network service is added.
