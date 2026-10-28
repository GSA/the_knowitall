# Revision-Bound Code-Context Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first local, deterministic Knowitall provider slice that turns synthetic Git snapshots into validated revision-bound Graphify generations and v1 symbol/dependency evidence packets.

**Architecture:** A contract package owns JSON Schema and validation, repository intake creates immutable content manifests, a pinned Graphify adapter produces normalized graph generations, a publication store atomically selects validated generations per repository, and a local query service returns engine-neutral packets. Each component follows an existing owning Kata and communicates only through the v1 identities and records defined by the approved spec.

**Tech Stack:** Python 3.12, JSON Schema Draft 2020-12, Git CLI, pinned `graphifyy` package/source artifact, pytest, synthetic Python and TypeScript Git fixtures.

**Spec:** `docs/superpowers/specs/2026-10-28-revision-bound-code-context-provider-design.md`

## Global Constraints

- One Knowitall deployment serves one configured project and may contain multiple explicitly identified repositories.
- Contract identifier is exactly `knowitall.code-context/v1`; unknown versions fail closed as `invalid_request`.
- Dirty Git input is rejected by default and, when explicitly enabled, receives a content identity distinct from its commit.
- Model/semantic enrichment and network access are disabled in the first Graphify integration.
- Never treat failed or excluded scope as authoritative absence, and never infer deletion from listing or extraction failure.
- Only validated immutable generations may be atomically published; failed or staged work cannot replace the last known good generation.
- Queries never silently truncate and never substitute across project, repository, snapshot, or generation identities.
- Do not add a graph database, hosted service, generic provider framework, UI, real project source, or SPUD pipeline dependency.
- Before adopting or redistributing Graphify, record the exact package hash, source revision, license identifier, notices, and compatibility result under `knowitall#r9gz`.
- Acquire-specific source, language, scale, and policy validation is deferred until an authorized Acquire deployment is cloned and configured.

## Review Focus

- Symlink, submodule, LFS, or path traversal input must remain within the admitted repository and must be accounted for as included, excluded, or failed by explicit policy; Task 2 tests these boundaries.
- A process interruption between artifact validation and publication must leave the previous generation current and permit idempotent recovery; Task 4 tests the publication boundary.
- Similar project/repository/snapshot IDs, Unicode paths, and duplicate symbol names must not cause fallback or normalization collisions; Tasks 1, 2, and 5 test exact identity handling.
- A continuation replayed against a different generation or query must fail as `invalid_request`, not leak or omit evidence; Task 5 binds continuations to the normalized request and generation.
- A Graphify success exit with malformed, incomplete, network/model-derived, or source-mismatched artifacts must fail validation or remain explicitly partial; Task 3 tests all five conditions.

---

## File map

| Path | Responsibility |
| --- | --- |
| `pyproject.toml` | Package metadata, exact Python floor, runtime/test dependencies, pytest configuration. |
| `src/knowitall_contract/` | V1 schemas, typed records, JSON validation, status/error vocabulary. |
| `src/knowitall_snapshot/` | Git inspection, safe inventory, immutable content manifest and snapshot materialization. |
| `src/knowitall_graphify/` | Pinned subprocess adapter, output normalization, generation validation and provenance. |
| `src/knowitall_publication/` | Filesystem generation layout, validation receipts, atomic per-repository current pointer. |
| `src/knowitall_query/` | Engine-neutral symbol/dependency query service, coverage/status rules, continuation binding. |
| `schemas/knowitall.code-context/v1/` | Published JSON Schemas for manifests, requests, responses and shared definitions. |
| `examples/knowitall.code-context/v1/` | Schema-valid clean manifest, exact request, success response, and partial response packets. |
| `tests/fixtures/repos/` | Tiny source templates used to create isolated Python/TypeScript Git histories during tests. |
| `tests/` | Contract, intake, adapter, publication, query and end-to-end conformance tests. |
| `docs/graphify-dependency.md` | Exact pin, package hash, source revision, license/notices, invocation and disabled routes. |
| `docs/local-provider.md` | Reproducible local synthetic setup and conformance commands; no project-specific configuration. |

### Task 1: Publish and Validate the V1 Contract

**Owning Kata:** `knowitall#8jvw` for consumer packets, coordinated with `engi-platform#ca6n` for shared examples.

**Files:**
- Create: `pyproject.toml`
- Create: `src/knowitall_contract/__init__.py`
- Create: `src/knowitall_contract/models.py`
- Create: `src/knowitall_contract/validation.py`
- Create: `schemas/knowitall.code-context/v1/common.schema.json`
- Create: `schemas/knowitall.code-context/v1/snapshot-manifest.schema.json`
- Create: `schemas/knowitall.code-context/v1/query-request.schema.json`
- Create: `schemas/knowitall.code-context/v1/query-response.schema.json`
- Create: `examples/knowitall.code-context/v1/clean-manifest.json`
- Create: `examples/knowitall.code-context/v1/exact-dependency-request.json`
- Create: `examples/knowitall.code-context/v1/dependency-response.json`
- Create: `examples/knowitall.code-context/v1/partial-response.json`
- Test: `tests/contract/test_schema_examples.py`
- Test: `tests/contract/test_validation.py`

**Interfaces:**
- Consumes: approved v1 design specification.
- Produces: `validate_manifest(value: Mapping[str, object]) -> None`, `validate_query_request(value: Mapping[str, object]) -> None`, `validate_query_response(value: Mapping[str, object]) -> None`; frozen records `SnapshotRef`, `GenerationRef`, `SourceRange`, `Coverage`, `MissingEvidence`, and `QueryStatus` used by later tasks.

- [ ] **Step 1: Write failing schema-example tests**

Add tests asserting that the approved clean manifest, exact dependency request, and successful response validate; and that an unknown contract, omitted project/repository identity, null required field, absolute/parent path, zero line/column, invalid digest, and duplicate final-scope path each fail with a stable validation error.

- [ ] **Step 2: Run contract tests and verify the missing schemas/API fail**

Run: `python3 -m pytest tests/contract/test_schema_examples.py tests/contract/test_validation.py -q`

Expected: FAIL because `knowitall_contract` and the v1 schemas do not exist.

- [ ] **Step 3: Implement the smallest v1 schemas and typed validation API**

Use Draft 2020-12 schemas with closed required v1 shapes and semantic checks in `validation.py` for disjoint path accounting, exact-selector field combinations, one-based half-open ranges, and opaque nonempty identity equality. Do not encode Graphify-native records.

- [ ] **Step 4: Run contract tests**

Run: `python3 -m pytest tests/contract -q`

Expected: PASS.

- [ ] **Step 5: Commit the contract package**

```bash
git add pyproject.toml schemas examples src/knowitall_contract tests/contract
git commit -m "feat: add code-context v1 contract schemas"
```

### Task 2: Create Immutable Git Source Snapshots

**Owning Kata:** `knowitall#7gv8`.

**Files:**
- Create: `src/knowitall_snapshot/__init__.py`
- Create: `src/knowitall_snapshot/git.py`
- Create: `src/knowitall_snapshot/inventory.py`
- Create: `src/knowitall_snapshot/materialize.py`
- Create: `tests/fixtures/repos/python_service/src/orders.py`
- Create: `tests/fixtures/repos/python_service/src/store.py`
- Create: `tests/fixtures/repos/typescript_client/src/client.ts`
- Create: `tests/fixtures/repos/typescript_client/src/api.ts`
- Create: `tests/snapshot/test_git_snapshot.py`
- Create: `tests/snapshot/test_inventory_safety.py`
- Create: `tests/snapshot/test_dirty_snapshot.py`

**Interfaces:**
- Consumes: `SnapshotRef` and manifest validation from Task 1.
- Produces: `SnapshotPolicy`, `SnapshotManifest`, and `create_snapshot(repo: Path, project_id: str, repository_id: str, destination: Path, policy: SnapshotPolicy) -> SnapshotManifest`; immutable materialized tree at `destination/<snapshot_id>/source` plus canonical manifest bytes.

- [ ] **Step 1: Write failing clean and multi-repository snapshot tests**

Create isolated Git repositories from fixture templates during tests. Assert stable repository identity across checkout moves, exact algorithm-qualified commit/content digests, deterministic inventory ordering, distinct snapshots for the two repositories, and no fallback when IDs differ only by case or Unicode representation.

- [ ] **Step 2: Run the clean snapshot tests and verify failure**

Run: `python3 -m pytest tests/snapshot/test_git_snapshot.py -q`

Expected: FAIL because `create_snapshot` is undefined.

- [ ] **Step 3: Implement clean snapshot inventory and materialization**

Invoke Git with hooks disabled and no source execution. Hash canonical path/content entries, copy only inventoried regular files into a temporary generation directory, validate the manifest, then rename it into its immutable snapshot path. Reject an existing identity whose bytes differ.

- [ ] **Step 4: Run clean snapshot tests**

Run: `python3 -m pytest tests/snapshot/test_git_snapshot.py -q`

Expected: PASS.

- [ ] **Step 5: Write failing safety and dirty-input tests**

Assert default rejection of tracked changes and untracked files; explicit dirty policy records tracked/untracked choices and a distinct dirty digest; escaping symlinks, absolute/`..` paths, nested Git repositories, submodules, and LFS pointers follow explicit policies without dereferencing unauthorized content; unreadable/listing failure leaves inventory incomplete and cannot assert deletions.

- [ ] **Step 6: Run safety tests and verify failure**

Run: `python3 -m pytest tests/snapshot/test_inventory_safety.py tests/snapshot/test_dirty_snapshot.py -q`

Expected: FAIL on unimplemented policy behavior.

- [ ] **Step 7: Implement explicit safety, submodule/LFS, and dirty policies**

Keep v1 defaults `submodules=exclude`, `lfs=pointers`, `dirty=reject`. Permit dirty admission only through explicit `SnapshotPolicy` values and bind actual included bytes to `dirty_content_digest`.

- [ ] **Step 8: Run all snapshot and contract tests**

Run: `python3 -m pytest tests/contract tests/snapshot -q`

Expected: PASS.

- [ ] **Step 9: Commit snapshot intake**

```bash
git add src/knowitall_snapshot tests/fixtures tests/snapshot
git commit -m "feat: create immutable git source snapshots"
```

### Task 3: Pin and Wrap Deterministic Graphify Extraction

**Owning Kata:** `knowitall#r9gz`.

**Files:**
- Modify: `pyproject.toml`
- Create: `requirements/graphify.lock`
- Create: `docs/graphify-dependency.md`
- Create: `src/knowitall_graphify/__init__.py`
- Create: `src/knowitall_graphify/adapter.py`
- Create: `src/knowitall_graphify/normalize.py`
- Create: `src/knowitall_graphify/validate.py`
- Create: `tests/graphify/fake_graphify.py`
- Create: `tests/graphify/test_adapter_boundaries.py`
- Create: `tests/graphify/test_generation_validation.py`
- Create: `tests/graphify/test_real_synthetic_extraction.py`

**Interfaces:**
- Consumes: immutable snapshot directory and `SnapshotManifest` from Task 2.
- Produces: `GraphifyConfig`, `GraphGeneration`, and `extract_generation(snapshot: SnapshotManifest, source_dir: Path, staging_dir: Path, config: GraphifyConfig) -> GraphGeneration`; normalized immutable node/edge artifact plus generation manifest.

- [ ] **Step 1: Verify and document the dependency before adoption**

Record package filename/version/hash, source revision, license identifier, included notices, package-to-source correspondence, Python compatibility, and the exact code-only invocation. If rights or correspondence cannot be verified, comment on `knowitall#r9gz` and stop for owner review rather than adding the dependency.

- [ ] **Step 2: Write failing subprocess-boundary tests using the fake executable**

Assert an isolated environment, source/output path confinement, timeout/error capture, no shell, no inherited model/API credentials or proxy/network configuration, and explicit code-only/model-disabled arguments.

- [ ] **Step 3: Run adapter-boundary tests and verify failure**

Run: `python3 -m pytest tests/graphify/test_adapter_boundaries.py -q`

Expected: FAIL because the adapter does not exist.

- [ ] **Step 4: Implement the subprocess adapter and exact dependency lock**

Construct an allowlisted environment and argv, run only the pinned executable, retain bounded stdout/stderr receipts, and never interpret exit zero as generation validity.

- [ ] **Step 5: Write failing generation validation tests**

Cover malformed graph JSON, missing source locators, dangling edge endpoints, artifact digest mismatch, source snapshot mismatch, unaccounted files, partial parser output, and output claiming generated/model evidence while enrichment is disabled.

- [ ] **Step 6: Run generation tests and verify failure**

Run: `python3 -m pytest tests/graphify/test_generation_validation.py -q`

Expected: FAIL on unimplemented normalization/validation.

- [ ] **Step 7: Implement normalized generation creation and validation**

Normalize Graphify records behind v1 symbol, edge, locator, and coverage records; preserve Graphify's raw artifact by digest; mark parser failures partial; reject malformed/source-mismatched artifacts before publication eligibility.

- [ ] **Step 8: Add real pinned offline Python/TypeScript extraction tests**

Assert known Python call and TypeScript import/call edges with exact source ranges, deterministic output for repeat input, no model/network route, and exact extractor/runtime/config identity. Mark the test skipped only when the separately verified pinned artifact is not installed; CI and acceptance environments must install it.

- [ ] **Step 9: Run Graphify, snapshot, and contract tests**

Run: `python3 -m pytest tests/contract tests/snapshot tests/graphify -q`

Expected: PASS with real extraction tests executed in the acceptance environment.

- [ ] **Step 10: Commit the pinned adapter**

```bash
git add pyproject.toml requirements docs/graphify-dependency.md src/knowitall_graphify tests/graphify
git commit -m "feat: add pinned deterministic graph extraction"
```

### Task 4: Validate and Atomically Publish Generations

**Owning Kata:** `knowitall#regc`.

**Files:**
- Create: `src/knowitall_publication/__init__.py`
- Create: `src/knowitall_publication/store.py`
- Create: `src/knowitall_publication/validate.py`
- Create: `tests/publication/test_atomic_publication.py`
- Create: `tests/publication/test_recovery.py`
- Create: `tests/publication/test_changed_deleted_files.py`

**Interfaces:**
- Consumes: validated `SnapshotManifest` and `GraphGeneration` from Tasks 2 and 3.
- Produces: `PublicationStore(root: Path)`, `stage(generation) -> StagedGeneration`, `publish(staged) -> PublicationReceipt`, `resolve_current(project_id: str, repository_id: str) -> GenerationRef`, and `open_generation(ref: GenerationRef) -> GraphGeneration`.

- [ ] **Step 1: Write failing atomic publication tests**

Assert staging is not queryable, publication requires all manifest/artifact/schema/edge/coverage checks, current selection is per project/repository, exact retry is idempotent, and the same identity with different bytes conflicts.

- [ ] **Step 2: Run atomic tests and verify failure**

Run: `python3 -m pytest tests/publication/test_atomic_publication.py -q`

Expected: FAIL because `PublicationStore` is undefined.

- [ ] **Step 3: Implement staged layout and atomic current-pointer replacement**

Use same-filesystem temporary paths, fsync files/directories where supported, immutable generation directories, and an atomic pointer/metadata rename. Never mutate a published generation.

- [ ] **Step 4: Write failing interruption and recovery tests**

Inject failure before validation, after validation, before current-pointer replacement, and after replacement. Assert last-known-good identity remains truthful, recovery deduplicates completed work, and no half-written generation opens.

- [ ] **Step 5: Write failing changed/renamed/deleted path tests**

Create successive fixture commits. Assert changed/renamed paths get new snapshot/generation identities and content locators; deletion removes nodes/edges only with complete inventory or authoritative Git delta; parser/listing failure does not reconcile deletion.

- [ ] **Step 6: Run recovery/update tests and verify failure**

Run: `python3 -m pytest tests/publication/test_recovery.py tests/publication/test_changed_deleted_files.py -q`

Expected: FAIL on unimplemented recovery/update rules.

- [ ] **Step 7: Implement validation receipts, recovery, and truthful deletion reconciliation**

Persist stage state before publication, bind receipts to all input/output hashes, and use complete inventory or exact Git revision delta as the only deletion authority.

- [ ] **Step 8: Run publication and upstream component tests**

Run: `python3 -m pytest tests/contract tests/snapshot tests/graphify tests/publication -q`

Expected: PASS.

- [ ] **Step 9: Commit publication support**

```bash
git add src/knowitall_publication tests/publication
git commit -m "feat: publish graph generations atomically"
```

### Task 5: Serve Revision-Bound Symbol and Dependency Queries

**Owning Kata:** `knowitall#8jvw`.

**Files:**
- Create: `src/knowitall_query/__init__.py`
- Create: `src/knowitall_query/service.py`
- Create: `src/knowitall_query/continuation.py`
- Create: `src/knowitall_query/status.py`
- Create: `tests/query/test_exact_and_current.py`
- Create: `tests/query/test_status_semantics.py`
- Create: `tests/query/test_ambiguity_and_isolation.py`
- Create: `tests/query/test_continuation.py`

**Interfaces:**
- Consumes: `PublicationStore` from Task 4 and v1 request/response validation from Task 1.
- Produces: `QueryService(store: PublicationStore, page_size: int)`, `execute(request: Mapping[str, object]) -> dict[str, object]`; exact v1 symbol and dependency response packets.

- [ ] **Step 1: Write failing exact/current selector tests**

Assert exact historical with `allow_historical`, exact current with `require_current`, stale exact selection, mutable current resolution with immutable echoed identities, unavailable generations, and project/repository mismatch without fallback.

- [ ] **Step 2: Run selector tests and verify failure**

Run: `python3 -m pytest tests/query/test_exact_and_current.py -q`

Expected: FAIL because `QueryService` is undefined.

- [ ] **Step 3: Implement selector resolution and response identity echo**

Validate before lookup; resolve only the selected project/repository; bind responses to snapshot, commit, content manifest, generation and artifact digests.

- [ ] **Step 4: Write failing status, ambiguity, and isolation tests**

Assert `ok`, coverage-qualified `not_found`, `partial` with failed/excluded relevant scope, `ambiguous` candidates, `unavailable`, `invalid_request`, duplicate symbol names in one repository, and same symbol names across two repositories. Ensure generated narrative/inference cannot appear as deterministic extraction.

- [ ] **Step 5: Run status/isolation tests and verify failure**

Run: `python3 -m pytest tests/query/test_status_semantics.py tests/query/test_ambiguity_and_isolation.py -q`

Expected: FAIL on unimplemented status mapping.

- [ ] **Step 6: Implement symbol/dependency lookup and coverage-derived statuses**

Return one-based half-open locators with file digest, deterministic ordering, explicit candidates/missing evidence, and `not_found` only when relevant inventory/extraction coverage is complete.

- [ ] **Step 7: Write failing continuation tests**

Assert complete untruncated responses, explicit truncation plus opaque continuation, deterministic next page, and rejection when a token is altered or replayed against another request, project, repository, snapshot, generation, or page size.

- [ ] **Step 8: Run continuation tests and verify failure**

Run: `python3 -m pytest tests/query/test_continuation.py -q`

Expected: FAIL because continuation binding is absent.

- [ ] **Step 9: Implement bound continuation tokens**

Encode or store an opaque token bound to the canonical normalized query, resolved generation, ordering key and page size; validate it before opening evidence. Do not silently truncate.

- [ ] **Step 10: Run all query and component tests**

Run: `python3 -m pytest tests/contract tests/snapshot tests/graphify tests/publication tests/query -q`

Expected: PASS.

- [ ] **Step 11: Commit query support**

```bash
git add src/knowitall_query tests/query
git commit -m "feat: query revision-bound code evidence"
```

### Task 6: Prove the Local Synthetic Vertical Slice

**Owning Katas:** Component evidence remains on `knowitall#7gv8`, `#r9gz`, `#8jvw`, and `#regc`; shared fixture compatibility is coordinated through `engi-platform#ca6n`.

**Files:**
- Create: `tests/conformance/test_provider_vertical_slice.py`
- Create: `tests/conformance/test_counterexamples.py`
- Create: `docs/local-provider.md`
- Create: `scripts/check-contract-examples.py`

**Interfaces:**
- Consumes: all component APIs from Tasks 1–5.
- Produces: one documented offline command and bounded test receipts proving the synthetic v1 provider slice; no stable external transport is introduced by this task.

- [ ] **Step 1: Write the failing end-to-end conformance test**

Create temporary Python and TypeScript Git repositories, snapshot each, extract with the real pinned engine, publish, then query known call/import evidence. Assert exact project/repository/snapshot/generation/artifact/content identities and line ranges in schema-valid packets.

- [ ] **Step 2: Write failing counterexample tests**

Cover wrong repository, ambiguous symbol, missing symbol under complete coverage, parser failure, changed file, deleted file, interrupted build, dirty default rejection, and bounded pagination without silent truncation.

- [ ] **Step 3: Run conformance tests and verify any integration failures**

Run: `python3 -m pytest tests/conformance -q`

Expected: FAIL until component wiring and real pinned extraction satisfy the full contract.

- [ ] **Step 4: Add only the minimal wiring and documentation needed for the local slice**

Document exact prerequisites, dependency integrity check, isolated temporary state, offline invocation, expected receipts, and cleanup. State that synthetic success is not Acquire validation or production readiness.

- [ ] **Step 5: Validate checked-in JSON examples and all tests**

Run: `python3 scripts/check-contract-examples.py && python3 -m pytest -q`

Expected: example validation succeeds and all tests PASS with no unexpected skips; the pinned real Python/TypeScript extraction tests execute.

- [ ] **Step 6: Run packaging, static, and whitespace checks**

Run: `python3 -m build && python3 -m compileall -q src tests scripts && git diff --check`

Expected: wheel and source distribution build, compilation exits zero, and whitespace check is clean.

- [ ] **Step 7: Commit vertical-slice evidence**

```bash
git add tests/conformance docs/local-provider.md scripts/check-contract-examples.py
git commit -m "test: prove synthetic provider vertical slice"
```

- [ ] **Step 8: Request whole-branch roborev and address findings additively**

Run: `roborev review --help` to select the supported branch/range invocation, submit the full implementation range, wait for completion, and record exact job/commit evidence on the owning Katas. Fix each accepted finding in a new commit; do not amend reviewed commits.

- [ ] **Step 9: Re-run final acceptance after review fixes**

Run: `python3 scripts/check-contract-examples.py && python3 -m pytest -q && python3 -m build && git diff --check`

Expected: all checks pass at the final reviewed HEAD, with clean working tree and no owned temporary process/state left behind.
