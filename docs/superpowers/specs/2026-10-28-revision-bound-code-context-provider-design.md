# Revision-Bound Code-Context Provider Design

**Status:** Proposed contract for owner review

**Contract version:** `knowitall.code-context/v1`

**Owning task:** `knowitall#vky6`

**Parent milestone:** `engi-platform#pyzt`

## Purpose and deployment boundary

Knowitall provides revision-bound code structure and source evidence to Engineer. A Knowitall deployment is reproduced and configured for one project. A project may contain multiple repositories whose revisions advance independently. Every request and response therefore names the project, repository, and source snapshot; a deployment must not substitute evidence across those boundaries.

This design is engine-neutral at the consumer boundary. The first implementation should wrap a pinned Graphify release rather than expose Graphify-native records or build another parser, graph database, provider framework, or UI.

The initial conformance fixtures are synthetic Python and TypeScript repositories. Acquire-specific repositories, language coverage, scale validation, and source policy are deferred until an authorized Acquire Knowitall deployment is cloned and configured.

## Authority and non-goals

Knowitall is authoritative for admitted source bytes, immutable source manifests, generated code-graph artifacts, extraction provenance, publication state, and reported extraction coverage. It does not establish runtime behavior, business intent, or business truth.

The Librarian owns business assertions and their evidence/disposition. Engineer composes both providers' evidence without becoming another source of truth. SPUD may supply attributed technical artifacts through a later optional adapter; this contract does not require a SPUD redesign.

Version 1 does not include real source acquisition, hosted multi-tenancy, semantic/model enrichment, generated documentation, business-to-code assertion lifecycle, cloud deployment, or an organization-wide repository crawler.

## Identity model

All identifiers are opaque, nonempty strings. Display names and checkout paths are never identity.

| Identity | Required fields | Rule |
| --- | --- | --- |
| Project | `project_id`, `project_name` | One deployment serves one configured project. `project_id` is stable across deployment reproduction. |
| Repository | `repository_id`, `repository_name`, optional canonical origin | Unique within a project and stable across checkout path or origin URL changes. Origin is provenance, not identity. |
| Source snapshot | `snapshot_id`, exact `commit`, `content_manifest_digest`, cleanliness and dirty policy | Identifies the bytes admitted for extraction. Commit alone is sufficient only when the admitted manifest matches the clean commit tree under the declared submodule/LFS policy. |
| Graph generation | `generation_id`, source snapshot reference, extractor/config/runtime identities, artifact digests | Immutable. Different source bytes, extractor/config/runtime identities, or graph artifacts produce a different generation. |
| Publication | repository plus generation and publication timestamp | Only a validated immutable generation may be published. `current` is a mutable selector, never an evidence identity. |

A deliberately admitted dirty snapshot records `dirty_content_digest`, tracked-change policy, untracked-file policy, and the resulting content manifest. It must never be represented by `commit` alone. Dirty input is rejected by default.

Digest strings use an algorithm-qualified form such as `sha256:<lowercase-hex>`. Git object IDs retain their native algorithm-qualified form, for example `sha1:<hex>` or `sha256:<hex>`.

## Versioned envelope

Every request and response includes:

```json
{
  "contract": "knowitall.code-context/v1",
  "request_id": "opaque-caller-correlation-id",
  "project_id": "project-acquire",
  "repository_id": "inventory-api"
}
```

Unknown contract versions fail with `invalid_request`; implementations must not guess compatibility. Unknown fields may be retained in transport but do not alter v1 meaning. Fields defined as required may not be omitted or replaced with `null`.

## Snapshot manifest

A validated generation references an immutable snapshot manifest with this logical shape:

```json
{
  "contract": "knowitall.code-context/v1",
  "project": {
    "project_id": "project-synthetic",
    "project_name": "Synthetic conformance project"
  },
  "repository": {
    "repository_id": "repo-python-service",
    "repository_name": "Python service",
    "origin": "fixture://python-service"
  },
  "source": {
    "snapshot_id": "snap-python-0001",
    "vcs": "git",
    "commit": "sha1:1111111111111111111111111111111111111111",
    "content_manifest_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "cleanliness": "clean",
    "dirty": null,
    "submodules": {"policy": "exclude", "entries": []},
    "lfs": {"policy": "pointers", "objects_resolved": false}
  },
  "scope": {
    "inventory_complete": true,
    "included": [
      {"path": "src/orders.py", "content_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "status": "extracted"}
    ],
    "excluded": [
      {"path": "vendor/", "reason": "configured_exclusion"}
    ],
    "failed": []
  },
  "extraction": {
    "engine": "graphify",
    "engine_version": "0.9.96",
    "engine_source_revision": "sha1:dac063456bc1f5d92354ec3936fd9dd1513a83f3",
    "runtime": {"name": "python", "version": "3.12.7"},
    "config_digest": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "model_enrichment": "disabled"
  },
  "graph": {
    "generation_id": "gen-python-0001",
    "artifact_digest": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "schema_version": "example-graph-schema/v1",
    "state": "complete"
  },
  "coverage": {
    "inventory": "complete",
    "extraction": "complete",
    "languages": [
      {"language": "python", "files_discovered": 1, "files_extracted": 1, "files_failed": 0}
    ],
    "limitations": []
  }
}
```

The runtime and graph-schema values above are examples of exact values. A producer must emit the values actually used and must not copy the examples unless they are true for that generation.

`scope.included`, `scope.excluded`, and `scope.failed` account for the complete discovered inventory when `inventory_complete` is true. A path cannot occur in more than one final category. Exclusion is an explicit policy result, not extraction success. A failed listing makes inventory incomplete and prevents an authoritative deletion or repository-wide absence claim.

`graph.state` is `complete` only when the declared inventory and extraction obligations are satisfied. Otherwise it is `partial`; blocked and failed build attempts are recorded in the producer ledger but are not valid generations for publication.

## Query request

Version 1 supports four query kinds:

- `symbol`: definitions matching an exact or implementation-declared normalized name;
- `dependencies`: typed incoming or outgoing graph relationships for an identified symbol;
- `path`: evidence associated with a repository-relative path;
- `source_range`: symbols and recorded relationships intersecting an exact source range.

```json
{
  "contract": "knowitall.code-context/v1",
  "request_id": "req-42",
  "project_id": "project-synthetic",
  "repository_id": "repo-python-service",
  "selector": {
    "mode": "exact",
    "snapshot_id": "snap-python-0001",
    "generation_id": "gen-python-0001",
    "freshness": "allow_historical"
  },
  "query": {
    "kind": "dependencies",
    "symbol_id": "python:src/orders.py:submit_order",
    "direction": "outgoing",
    "relationship_kinds": ["calls", "imports"]
  }
}
```

`selector.mode` is either `exact` or `current`. Exact mode requires both snapshot and generation IDs and a `freshness` value of `allow_historical` or `require_current`; it fails closed on any identity mismatch. `require_current` returns `stale` if that exact generation is valid but no longer current, while `allow_historical` permits a query of a still-retained older generation. Current mode omits snapshot, generation, and freshness fields and resolves the repository's currently published generation at request evaluation time. Every response echoes the exact resolved identities; downstream evidence must store those identities rather than the word `current`.

Implementations may enforce documented safety bounds for traversal depth or response size. They must not silently truncate. A bounded response either returns all matching evidence, supplies an opaque continuation with `truncated: true`, or returns an explicit non-success state when complete requested evidence cannot be represented. Ordering and continuation stability are defined by the implementation and recorded in conformance tests; consumers must not infer completeness from a nonempty result.

## Query response

```json
{
  "contract": "knowitall.code-context/v1",
  "request_id": "req-42",
  "project_id": "project-synthetic",
  "repository_id": "repo-python-service",
  "resolved": {
    "snapshot_id": "snap-python-0001",
    "commit": "sha1:1111111111111111111111111111111111111111",
    "content_manifest_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "generation_id": "gen-python-0001",
    "artifact_digest": "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  },
  "status": "ok",
  "coverage": {
    "inventory": "complete",
    "extraction": "complete",
    "relevant_scope": "complete",
    "limitations": []
  },
  "evidence": [
    {
      "evidence_id": "edge-submit-to-save",
      "grade": "deterministic_extraction",
      "kind": "calls",
      "subject": {"symbol_id": "python:src/orders.py:submit_order", "name": "submit_order"},
      "object": {"symbol_id": "python:src/store.py:save_order", "name": "save_order"},
      "locator": {
        "path": "src/orders.py",
        "start": {"line": 8, "column": 5},
        "end": {"line": 8, "column": 24},
        "content_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
      }
    }
  ],
  "ambiguities": [],
  "missing_evidence": [],
  "truncated": false,
  "continuation": null
}
```

Lines and columns are one-based. Ranges are half-open: start is inclusive and end is exclusive. Repository-relative paths use `/`, contain no empty, `.` or `..` segment, and never begin with `/`. Locators include the file content digest so line evidence is bound to bytes as well as a generation.

Evidence grades are:

- `deterministic_extraction`: emitted by configured code-only extraction from admitted bytes;
- `recorded_artifact`: supplied by an attributed admitted artifact without rerunning its producer;
- `generated_narrative`: generated explanatory text, never a graph fact by itself;
- `inference`: a declared inference, never presented as extracted runtime or business behavior.

Initial Graphify integration emits `deterministic_extraction` only. Later adapters may use other grades but cannot silently promote them.

## Status and failure semantics

The response `status` is one of:

| Status | Meaning |
| --- | --- |
| `ok` | Complete answer for the requested query within declared complete relevant scope. |
| `partial` | Some evidence is usable, but failed, excluded, unparsed, truncated, or unknown relevant scope prevents a complete answer. `missing_evidence` and coverage limitations are required. |
| `not_found` | No match exists within declared successfully inventoried and extracted relevant scope. It is not valid when relevant scope is failed, excluded, or unknown. |
| `ambiguous` | Multiple identities or interpretations satisfy a request that requires one. Candidates and disambiguating evidence are returned without choosing one. |
| `stale` | An exact selector used `require_current`, and its valid generation is no longer the repository's current publication. The older identity may be reported, but its evidence is not returned as current fact. |
| `unavailable` | Required snapshot, generation, artifact, or coverage evidence cannot be queried. |
| `invalid_request` | Contract version, identity, selector, range, query shape, or continuation is invalid. |

Transport failure is distinct from a valid response status. Consumers retry transport and declared transient unavailability only under their own bounded policy; they do not reinterpret malformed or partial responses as success.

`missing_evidence` contains machine-readable entries with `kind`, `scope`, and `reason`, for example a failed parser path, unresolved LFS object, excluded submodule, absent SPUD companion artifact, or incomplete inventory. Empty evidence with `partial` is valid and materially different from `not_found`.

## Freshness and publication

A generation is staged, schema-validated, checked for source binding, artifact integrity, edge endpoint validity, and truthful coverage before one atomic publication action makes it current. In-progress, blocked, failed, or half-written generations are never queryable as published generations.

Failure to produce a new generation leaves the last known good publication available with its actual older snapshot and generation identities. It must not be relabeled with the requested commit or described as fresh.

Changed, renamed, and deleted paths produce a new source snapshot and graph generation. A deletion may be asserted only from a complete inventory or an authoritative version-control change record bound to both revisions. Listing or extraction failure never implies deletion. Exact repeat publication is idempotent; the same identity with different bytes or artifact hashes is a conflict, not an update.

Consumers that require a particular revision use exact mode. Consumers that elect current mode must compare and retain the returned identities before acting. A project may publish independent current generations for each repository; there is no implied atomic cross-repository revision set in v1.

## Consumer obligations

Engineer and other consumers must:

1. select the intended project and repository explicitly;
2. use exact mode when a task is bound to a known revision;
3. retain the resolved snapshot, commit, content manifest, generation, artifact, locator, and evidence grade with derived work;
4. reject identity mismatch, stale, unavailable, invalid, and required-context partial responses rather than substituting another repository or generation;
5. display partial coverage, ambiguity, missing evidence, and inference grades to reviewers;
6. treat `not_found` only as absence within the response's declared coverage; and
7. revalidate relevant snapshot identities before execution or review when freshness matters.

A business-to-code association references these code identities but remains a Librarian-owned assertion with its own evidence and disposition.

## First implementation slice

The approval-ready first slice is deliberately narrow:

1. admit synthetic local Git fixtures into immutable clean source snapshots;
2. invoke a pinned Graphify adapter in deterministic code-only mode with model and network enrichment disabled;
3. validate and atomically publish an immutable graph generation;
4. expose local symbol and dependency queries through this envelope; and
5. verify Python and TypeScript known answers and counterexamples.

The slice should be split across existing owning tasks: `knowitall#7gv8` for intake/snapshots, `knowitall#r9gz` for Graphify integration, `knowitall#8jvw` for queries, and `knowitall#regc` for updates/publication. `knowitall#axsf` remains a later optional SPUD-artifact adapter. This design does not authorize starting those tasks.

## Synthetic conformance scenarios

The shared fixture work may refine file names, but it must preserve these behaviors:

| Scenario | Required observation |
| --- | --- |
| Python known dependency | `submit_order` calls `save_order`; response includes typed edge and exact call-site range. |
| TypeScript known import/call | A consumer imports and calls an exported function; both relationships retain TypeScript source ranges. |
| Same symbol name in two repositories | Repository selection returns only the selected repository; omission or wrong identity is invalid/unavailable, never cross-repository fallback. |
| Ambiguous symbol in one repository | `ambiguous` returns candidates without selecting one. |
| Missing symbol under complete coverage | `not_found` with complete relevant coverage. |
| Parser failure in relevant path | `partial` or `unavailable`, failed path in `missing_evidence`; never authoritative `not_found`. |
| Changed file | New snapshot/generation and locator content digest; exact old query remains old, while current resolves new. |
| Deleted file | New generation omits prior nodes/edges only after complete inventory or authoritative change evidence. |
| Interrupted/failed build | Last known good remains published under its old identity; staged generation is not visible. |
| Dirty input | Rejected by default; explicitly enabled case has dirty digest/policy and cannot equal clean snapshot identity. |
| Silent truncation attempt | Response has continuation and `truncated: true`, or explicit partial/non-success; never plain `ok` implying completeness. |

Fixtures contain no real project code or business corpus. Passing them proves contract behavior, not representative Acquire language support, production scale, or real-source authorization.

## Engine choice, pin, and reuse rights

The inspected candidate baseline is Graphify-Labs/graphify source revision `dac063456bc1f5d92354ec3936fd9dd1513a83f3`, corresponding to package `graphifyy` 0.9.96. Prior bounded offline evidence exercised Python and TypeScript extraction, query direction, incremental updates, and deleted-file/edge behavior. This is evidence for selection, not proof of every language, deployment, or current upstream release.

The implementation should pin an immutable package artifact and hash plus its source revision, retain its license files and notices, and record the exact runtime/configuration. No Graphify or SPUD source is copied by this design. Repository inspection found Graphify license files, but the exact package-to-source license/notice and redistribution obligations remain a visible pre-integration gate: `r9gz` must verify and record them before dependency adoption or redistribution. Failure of that check requires selecting a compatible pinned release or stopping for owner review; it does not authorize copying code.

## Decisions and visible unknowns

Decided:

- one reproducible Knowitall deployment per project;
- multiple explicitly identified repositories per project;
- immutable source and graph generations with atomic per-repository publication;
- JSON v1 envelope and typed query results independent of Graphify internals;
- deterministic code-only Graphify candidate for the first slice;
- synthetic Python and TypeScript conformance now; Acquire validation later; and
- explicit partial, stale, ambiguous, unavailable, and missing-evidence behavior.

Deferred to implementation planning or an authorized project instance:

- exact implementation language and local CLI/MCP transport;
- storage layout and retention policy;
- final JSON Schema file decomposition and continuation encoding;
- exact Graphify artifact hash, runtime version, graph schema, license identifier, and notices after package verification;
- project-specific repository allowlist, submodule/LFS policy, languages, scale, and freshness requirements;
- deployment-attested runtime integrity for extractor execution, tracked as `knowitall#d2qt`: this slice verifies extractor package and version identity, not host, loader, or filesystem attestation; and
- cross-repository release-set semantics, semantic enrichment, hosted access control, and SPUD artifact admission.

None of these deferred choices permits weakening identity, coverage, publication, or failure semantics defined here.

## Acceptance mapping

| `knowitall#vky6` acceptance | Design coverage |
| --- | --- |
| Repository/project, revision and dirty-content identity | Identity model and snapshot manifest |
| Extractor/runtime/version and graph/artifact identity | Snapshot manifest; engine choice and pin |
| Included/excluded/failed scope and coverage | Snapshot manifest; status semantics |
| Source file/line evidence | Query response and locator rules |
| Partial/stale/error/missing evidence | Status and failure semantics |
| Deterministic extraction versus narrative/inference | Evidence grades and authority boundary |
| Known symbol/dependency and changed/deleted files | Synthetic conformance scenarios |
| No fabricated completeness or arbitrary silent limits | Query bounds, coverage, and truncation rules |
| Existing engine/version/reuse-rights choice | Graphify candidate baseline and pre-integration license gate |
| Approval-ready first integration slice | First implementation slice and owning-task split |
| Representative project/language agreement before build | Synthetic Python/TypeScript now; project-specific validation explicitly deferred until deployment configuration |
