# The Knowitall

Code context and revision-bound repository knowledge graphs for engineering.

**Status: design/bootstrap, October 27, 2026.** This repository currently holds
the product direction and native Kata binding, not a working graph service,
populated code corpus or permission to acquire new source assets.

## Why this repository exists

The original plan used SPUD for technical context alongside The Librarian and
The Engineer. Implementation inspection found valuable components, but SPUD's
documentation factory also crosses our desired document-acquisition and
code-context boundaries. Its original engineer may reasonably prefer that
product direction. We should not depend on reshaping it into our entire system.

The owner therefore establishes a separate code-context product. This supersedes
the earlier recommendation to avoid another top-level repository. The goal is
to compose effective components, not rewrite parsers, duplicate an upstream
project, or make a renamed SPUD fork.

| Product | Owns | Does not own |
| --- | --- | --- |
| **The Knowitall** | Authorized repository intake, immutable source snapshots, code graph production, technical provenance, revision/coverage-aware queries | Business truth, document-corpus qualification, task execution or agent memory |
| **The Librarian** | Business-source intake, originals/renditions, entities/claims and evidence-backed relationships, qualification, corrections and retrieval | Code parsing/graph production, task authority or coding-agent memory |
| **The Engineer** | Kata issues, Forge workspaces/agents/PRs, roborev review, AgentsView visibility, selective agent-event memory and consumption of both context providers | Either provider's source authority or ingestion engine |
| **SPUD** | Its independently maintained documentation/analysis product | Our future cross-product authority or mandatory orchestration layer |

Routing follows purpose rather than file extension. A repository README can be
technical context; a business rule in that repository can also be admitted by
Librarian with the same source/version reference. Sharing references must not
silently create conflicting authoritative copies.

## What we learned from SPUD

Inspected source baseline: SPUD `c80837a`, SPUD Web `8e9626d`, Graphify
`dac063456bc1f5d92354ec3936fd9dd1513a83f3` (package 0.9.96), Confluence exporter
v0.2.4 `b310442e22b9501c2527fa344ef272185e427e50`, Jira exporter v0.3.4
`7894cba1de887452667d1e54594df13f878e1686`. These are research pins, not proof of
deployed versions or final runtime selections.

- Graphify already provides typed graphs, source locators, deterministic
  code-only extraction, incremental updates/deletions and query/MCP operations.
  SPUD's flat citation index is not the full underlying graph.
- Jira and Confluence exporters already exist as independent packages, retaining
  useful raw JSON, Markdown and attachments. They need no physical extraction
  from SPUD merely to be used.
- SPUD Web already supplies job queues and terminal-event DLQ handling. That is
  not a per-document/page/attachment completion and replay system.
- Source inspection and synthetic probes found success-shaped dispatch failures,
  incomplete-export watermark advancement, attachment errors under completed
  parents, and persistence failures that can retain success. Output presence
  alone does not establish completeness.
- Graphify has useful revision and partial-build safeguards, but SPUD installs
  it unpinned at runtime. Existing clone/upload metadata also needs to be bound
  to the graph actually published.

The audit context and evidence remain in Engineer's
`context/system-architecture.md` and `context/tools.md`. Upstream fixes are
welcome where maintainers accept them; our design must not assume that agreement.

## Reuse and extraction intentions

| Functionality | Destination / approach |
| --- | --- |
| Graphify parsing and graph queries | Knowitall dependency integration, pinned and wrapped in our snapshot/evidence contract; no new graph engine initially |
| Repository acquisition and graph publication | Knowitall-owned implementation, reusing Git and existing Graphify incremental behavior |
| Existing SPUD graph/technical outputs | Optional Knowitall admission adapter with explicit missing-companion/revision/coverage limitations |
| Jira/Confluence export and reconciliation | Librarian adapters over standalone exporters, with correctness fixes and independently durable retry/reconciliation |
| Docling extraction | Reuse the already delivered Librarian lifecycle; add missing qualified-retrieval admission, not another converter |
| Useful OKF metadata/rendition conventions | Librarian's receiving contract, if they preserve identity, evidence and fidelity; no mandatory HTML/ZIP/Eleventy step |
| Drive and manual file upload | Librarian source adapters feeding the same retained-original, receipt and processing lifecycle |
| SPUD narrative/site generation and AWS UI/orchestration | Not required dependencies; retain as optional producers/consumers when independently useful |

"Extract" means identify a reusable capability and integrate or port only what
is needed. Prefer public interfaces and independently versioned packages over
copying implementation. Verify license, maintenance and update obligations
before copying or redistributing any upstream code. No upstream code has been
copied into this repository.

## Repository ingestion and graph building

Proposed initial flow:

```text
approved local checkout / explicitly configured read-only remote
  -> resolve exact revision and source scope
  -> retain immutable snapshot + content/coverage manifest
  -> pinned deterministic Graphify extraction
  -> validate graph, provenance and coverage
  -> atomically publish a queryable snapshot
```

Start with Git and an explicit repository allowlist. Resolve a branch/tag to an
exact commit; a moving ref is not a snapshot identity. Default to clean inputs.
If dirty inputs are deliberately admitted, identify actual included bytes
separately from HEAD, including the chosen untracked-file policy.

The manifest should bind project/repository identity, origin, commit and content
digest, included/excluded/failed paths, extractor/config versions and artifact
hashes. Submodules and LFS require explicit policies and completeness accounting;
do not silently recurse, omit required content, or pretend a pointer is its file.
Do not run source hooks, builds, macros or instructions as part of acquisition.

Keep complete, partial, blocked and failed states distinct. New graphs are
staged and validated before replacing a published generation. Preserve the last
known good snapshot with its real revision, not a false current-status label.
Reconcile deletion only from a complete inventory or authoritative change record.
Resume interrupted work without overwriting evidence or duplicating publication.

Queries return symbols, relationships and source ranges with snapshot identity,
coverage, ambiguity and freshness. Extracted calls/imports are not proof of
runtime behavior or business intent. Optional semantic enrichment must identify
inference and use separately approved model/data routes.

No hosted graph database, multi-tenant server, organization-wide crawler or new
platform UI is selected as a prerequisite. Evaluate actual query and scale needs
before adding infrastructure.

## Librarian: engineering-useful business knowledge

The Librarian toolkit currently has an empty business corpus. Use that opportunity
to design a clean domain model rather than inherit FALCON-specific identities or
prematurely optimize a migration. Existing writers, provenance, corrections and
freshness protections remain valuable. Empty corpus does not authorize resetting
stores: verify actual contents and explicitly version any future schema change.

Candidate entity classes are capabilities, requirements/business rules,
processes, domain concepts/data definitions, roles, systems/integrations and
decisions. Choose the smallest set that answers concrete engineering questions:

- Which requirement or rule motivates a change, and what is its exact evidence?
- Which process, role, data definition or integration does it affect?
- Which decisions constrain implementation, and which claims conflict or expired?
- What code might implement it, at which revision, with what supporting evidence?

During ingestion, retain original/source identity first; normalize text and
structure second; then propose entities and typed assertions. Each assertion
needs source passage/locator and version, extraction/author identity, temporal
applicability, basis and review/correction state. Confidence is not verification.
Keep explicitly recorded facts, extracted assertions and inferred candidates
distinguishable. A parser or model run is not substantive business review.

Use stable project-scoped IDs and aliases, not titles as identity. Resolve
duplicates with evidence, preserve ambiguity, and retain merge/split and
correction history. Identical text or repeated sources are not independent
corroboration. Do not auto-merge same-named systems, people or requirements.

The first implementation slice should turn a passage into a business rule/entity
and an evidence-backed relationship, then support a bounded qualified query.
Build a derived/rebuildable navigation projection from accepted records or
attributed artifacts; do not make a graph database an accidental authority.
Reconcile Librarian's existing relationship-design decision before implementing
the selected slice. This is not a restart of graph-storage research.

Code symbols remain Knowitall-owned. Cross-product associations reference the
Librarian assertion and a Knowitall repository/snapshot/symbol identity. They
carry their own evidence and disposition; a shared name alone is not an
`implements` relationship. Engineer composes the answers without becoming a
third source of truth.

## Document intake shared by all sources

Drive, Atlassian exports and manual uploads should converge on:

```text
discover or submit -> private staging -> retain/register original
  -> format-routed normalization -> quality/knowledge processing
  -> policy qualification -> selected retrieval publication
```

The common runner owns durable stage work, saved requests, retry/backoff,
dead-letter inspection/replay and honest coverage. Existing catalog/review
writers retain authority. A drained queue or a file in a DLQ is not successful
ingestion. Connector-wide access failures pause that connector rather than
flooding the item queue. Automatic routine processing follows an approved
standing policy; human review handles consequential exceptions and conflicts.

Manual intake may start as a local CLI/drop-folder submission rather than a web
UI. Preserve who supplied the file, what origin/version is actually known and
its content hash. Do not invent a Drive identity from a filename. Reuse the same
normalization and recovery path rather than maintain a second upload pipeline.
Original binaries, page/table structure and extraction limitations must survive
text normalization; unreadable or over-budget inputs cannot silently succeed.

## Delivery and task authority

Native Kata project: `knowitall`, bound by `.kata.toml`. Use
`kata list --project knowitall` for current status; do not treat this document
as a competing progress ledger.

Existing provider design `knowitall#vky6` moved from SPUD with its identity and
history preserved. Code-context slices:

| Kata | Scope |
| --- | --- |
| `knowitall#7gv8` | Repository intake and immutable snapshots |
| `knowitall#r9gz` | Pinned Graphify integration |
| `knowitall#8jvw` | Revision-bound queries/evidence packets |
| `knowitall#regc` | Resumable updates and atomic publication |
| `knowitall#axsf` | Optional SPUD technical-artifact admission |

Engineer coordinates the overall work under `engi-platform#pyzt`; memory
runtime is `engi-platform#pbqn`, provider consumption is `engi-platform#k4mp`.
Librarian owns its ingestion/entity implementation backlog. Existing
`spud#3sv9 -> librarian#55nx` still supplies exporter/receiver evidence; it
does not make SPUD the future business-context product.

| Librarian Kata | Scope |
| --- | --- |
| `zqdh` | Qualified retrieval of selected Docling renditions |
| `1md4` | Durable intake stages, DLQ and replay |
| `rst9` | Retained-export importer after existing receiving design |
| `bj17` / `5bc5` | Confluence / Jira exporter reuse and reconciliation |
| `3sx1` | Drive discovery and reconciliation |
| `9hqs` | Manual upload and local-drop intake |
| `8a5h` | Ordinary UTF-8 normalization |
| `0nj8` | Standing-policy review, qualification and publication |
| `rjr5` | Acknowledged contribution/disposition transport |
| `pwhw` -> `xzkj` | Business entity/relationship contract -> first implementation slice |

Useful OKF receiving conventions stay in existing `librarian#55nx`; this is
not another schema or rendering task. All references name planned work;
native Kata owns current status and dependencies.

The target demonstration is:
**source passage -> business rule/entity -> evidence-linked code symbol ->
affected dependency -> Engineer change/review**, plus interrupted-run recovery
and a changed/deleted source without duplicate evidence or false freshness.

Keep FALCON's legacy corpus/services intact. Acquire code authorization does
not itself authorize its business documents or a model destination. No real
repositories, documents, credentials, memories or graph snapshots are seeded
by this bootstrap. This repository has no remote or publication requirement.
