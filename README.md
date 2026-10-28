# The Knowitall

Code context and revision-bound repository knowledge graphs for engineering.

**Status: design/bootstrap, October 27, 2026.** Public repository:
https://github.com/GSA/the_knowitall, tracked locally under Kata project
`knowitall` (`.kata.toml`).

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

