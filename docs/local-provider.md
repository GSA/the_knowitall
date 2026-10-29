# Local synthetic provider verification

This repository exposes a Python library slice, not a network service. The local
verification composes immutable Git snapshot intake, pinned offline Graphify
extraction, atomic publication, and revision-bound v1 dependency queries.

## Scope

The tests create temporary Git repositories from checked-in synthetic Python and
TypeScript files. They do not acquire, execute, or publish external source. A
passing run proves only this bounded synthetic contract. It is **not** validation
against Acquire, authorization to ingest Acquire, or evidence of production
readiness, scale, availability, or semantic completeness.

## Prerequisites and dependency integrity

Use Python 3.12 or newer. Install this project with its test dependencies in an
isolated environment. Install Graphify and its grammar runtime from the exact
artifacts recorded in [`graphify-dependency.md`](graphify-dependency.md) and
`requirements/graphify.lock`; verify hashes before installation. The accepted
engine is `graphifyy==0.9.96`. Do not substitute an unpinned package.

The test environment used for acceptance keeps dependencies under ignored local
state and points `KNOWITALL_GRAPHIFY_RUNTIME` at the root of a dedicated
virtual environment built from the complete lock with
`pip install --no-index --require-hashes --no-deps`. The adapter approves that
interpreter by digest, probes the 31 exact pinned distributions, and executes
only the fixed `extract ... --code-only --no-cluster` route with an allowlisted,
credential-free environment. It does not run source hooks, builds, macros, or
model routes.

This checks package and version identity for synthetic conformance only. It is
not host, loader, or filesystem attestation, and it is not a production
runtime-integrity claim; see
[`graphify-dependency.md`](graphify-dependency.md).

## Authorized repository intake

The library accepts either an explicitly supplied local Git checkout through
`create_snapshot(...)` or one explicitly configured remote through
`acquire_remote(origin, destination)`. Remote acquisition clones without tags
or submodules, or fetches and hard-resets an existing dedicated checkout to
`origin/HEAD`; it never discovers repositories. Interactive prompting and Git
credential helpers are disabled, and origins containing embedded credentials
are rejected. Callers provide stable project and repository IDs separately;
checkout paths and origin URLs are provenance, not identity.

Snapshot materialization reads committed blobs with hook-disabled Git, rejects
dirty input by default, preserves regular-file executable modes, records
symlink/submodule/LFS and inventory limitations, and publishes only by an atomic
rename after the complete manifest and source tree exist. Real repository
allowlists, credentials, retention, and storage locations require separate
approval; the synthetic tests do not contact a network.

## Offline verification

From the repository root, with isolated dependencies available on `PYTHONPATH`:

```sh
export PYTHONPATH="/absolute/path/to/test-dependencies:$PWD/src"
export KNOWITALL_GRAPHIFY_RUNTIME="/absolute/path/to/pinned-graphify-venv"
python3 scripts/check-contract-examples.py
python3 -m pytest -q
python3 -m build
python3 -m compileall -q src tests scripts
git diff --check
```

Expected receipts are:

- all four checked-in v1 JSON examples validate;
- the suite has no unexpected skip (the real-engine tests require the runtime
  variable and otherwise report an intentional skip);
- real Python and TypeScript extraction produces deterministic source-bound call
  evidence;
- response packets validate and echo exact project, repository, snapshot,
  commit/content-manifest, generation, and artifact identities;
- counterexamples preserve repository isolation, partial coverage, stale
  revisions, interruption safety, dirty-input rejection, and visible pagination;
- wheel and source distribution builds succeed.

Graphify can conservatively mark files without deterministic AST records as
partial. A partial result is successful evidence with explicit limitations, not
complete repository coverage. Extracted calls/imports are static evidence, not
proof of runtime behavior or business meaning.

## Resumable updates

The library consumes an already admitted `SnapshotManifest`; it does not grant
intake or execution authority. Example using an approved pinned runtime and a
private state root:

```python
from pathlib import Path
from knowitall_graphify import GraphifyConfig, executable_digest
from knowitall_publication import PublicationStore
from knowitall_updates import UpdateLedger, UpdateRunner

private = Path("/absolute/private/knowitall-state")
runtime = Path("/absolute/path/to/pinned-graphify-venv")
interpreter = runtime / "bin/python"
config = GraphifyConfig(
    executable=interpreter,
    python_path=str(runtime / "lib/python3.14/site-packages"),
    expected_executable_digest=executable_digest(interpreter),
)
store = PublicationStore(private / "publication")
ledger = UpdateLedger(private / "updates", store)
runner = UpdateRunner(ledger, config)
# snapshot is the manifest returned by authorized create_snapshot(...).
try:
    predecessor = store.resolve_current(snapshot.project_id, snapshot.repository_id)
except KeyError:
    predecessor = None  # explicitly require an empty selection
runner.submit("operator-owned-idempotency-key", snapshot,
              expected_current=predecessor)
status = runner.resume("operator-owned-idempotency-key")
assert ledger.inspect(status.request_id) == status
if status.phase == "published":
    receipt = status.receipt  # exact snapshot/generation, not a moving ref
else:
    print(status.phase, status.reasons)
```

Submit durably captures exact admitted source bytes, snapshot fields, predecessor,
and extraction identities. Reopening the same ledger and calling `resume` uses
those saved bytes, not a moving checkout. The same key with changed inputs raises
`UpdateConflict`. Extraction/config changes cannot reuse acknowledged work.
`requested`, `extracting`, `staged`, `published` and `blocked` are separate phases.
Fatal extraction/validation raises its error and records a retryable reason, not
successful completion. Incomplete inventory records `blocked` without selecting
or deleting. Valid excluded/unsupported paths produce qualified partial evidence.

A committed checkpoint retains Graphify's native graph/manifest together with
normalized evidence and digests. Interrupted workspace output is discarded;
only a validated compatible checkpoint can seed Graphify's incremental route.
An identical snapshot/config reuses its checkpoint; a new commit with identical
files still binds a new revision. Unresolved native placeholders without real
source evidence fail closed (policy follow-up `the_knowitall#88nk`).

`publish(..., expected_current=predecessor)` is conditional. Historical completed
requests return the saved original receipt without moving `current` backward;
conflicting unpublished requests must be explicitly resubmitted against a chosen
new predecessor. Query packets retain the v1 schema and real partial limitations.
Corrupt persisted evidence is rejected, never trusted because a directory exists.

Use one ledger per publication store on a local POSIX filesystem supporting
`flock`, atomic rename and directory fsync. The reentrant store lock serializes
mutations and extraction across processes; this is not a multi-host queue or
availability guarantee. Private roots must be operator-controlled and inaccessible
to untrusted writers; digests detect corruption, not adversarial re-signing.
Requests retain source and checkpoints indefinitely. Do not delete committed
requests/receipts while idempotent retries or incremental reuse are required.
Cleanup requires an explicit retention decision; no automatic garbage collector
or destructive repair is provided. Replace corrupt state only from known-good
retained evidence, preserving diagnostic copies privately.

## Local query transport

`QueryService` is the in-process API. `serve_stdio(service, input, output)` adds
a minimal local newline-delimited JSON boundary for Engineer or another local
consumer: each input line is one v1 request and produces exactly one compact v1
response line. Malformed JSON or a non-object request produces an explicit
`invalid_request` packet and does not terminate the stream. The service resolves
only atomically published generations, echoes immutable identities, and exposes
partial, stale, ambiguous, unavailable, and paginated results unchanged.

This adapter is not an MCP server, authenticated network endpoint, generic
provider framework, or deployment service. A future transport may wrap the same
v1 request/response API without changing evidence semantics.

## Temporary state and cleanup

Pytest creates repositories, snapshots, extraction output, and publication stores
under its temporary directory and removes them normally. The adapter subprocess
is bounded and synchronous; no service remains running. Remove only the isolated
local dependency/build directories you created (for example `.pytest_cache/`,
`build/`, and `dist/`) after verification. Never point cleanup at an approved
source checkout or a published operational store.
