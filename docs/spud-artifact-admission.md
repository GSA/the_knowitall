# Optional SPUD technical-artifact admission

`knowitall_spud` admits an **already produced** SPUD bundle as graded, queryable
evidence without adopting SPUD's pipeline. Admission reads retained files only.
It never runs SPUD or Graphify, never calls a model, never opens a socket or a
subprocess, never extracts an archive, and never executes anything from the
bundle. Admitting a bundle therefore does **not** claim that SPUD ran locally,
that the bundle is current, or that its source scope was complete.

Admission is optional and separate from `knowitall.code-context/v1`. The
code-context contract is reserved for revision-bound graphs this repository
produced itself; nothing here backfills a missing commit identity to fit it.

## Reader profile and pins

The reader profile is `spud-reader/v1`, pinned to the inspected upstream
baseline SPUD `c80837a825cd412699f0431ad368e14b85ec246b`, Graphify
`dac063456bc1f5d92354ec3936fd9dd1513a83f3` (`graphifyy==0.9.96`). The profile
describes the *formats this reader understands*. It is not the producer version
of a given bundle, and a pin never supplies provenance a caller did not supply:
without a supplied `generator_version` the bundle carries the
`unknown_generator_version` limitation.

## Admission descriptor

A caller supplies identity, layout and provenance; the adapter never guesses
any of them. Descriptor version: `knowitall.spud-admission/v1`.

| Key | Meaning |
| --- | --- |
| `descriptor_version` | Must equal `knowitall.spud-admission/v1` |
| `project_id`, `repository_id`, `bundle_id` | Caller-owned identity; admission is scoped per project and repository |
| `layout` | `current`, `legacy`, `auto` or `explicit` |
| `artifacts` | Role/path selection; required for `explicit`, forbidden otherwise |
| `supplied` | Caller-asserted provenance strings (for example `generator_version`, `commit_sha`) |
| `expected_digests` | Optional `path -> sha256:<64 hex>` checks against retained bytes |
| `declared_missing` | Caller-declared `(scope, reason)` limitations, preserved verbatim; each reason must come from `LIMITATION_REASONS` |
| `source_binding` | Optional binding of the graph to an exact snapshot (see below) |

Paths must be bundle-relative and normal: absolute paths, `..` segments and
symlinks are rejected, so a descriptor cannot read outside the bundle root.

```python
from pathlib import Path
from knowitall_spud import AdmissionStore, load_descriptor, resolve_artifacts, read_bundle, normalize_bundle, BundleLimits

descriptor = load_descriptor({
    "descriptor_version": "knowitall.spud-admission/v1",
    "project_id": "project-a", "repository_id": "repo-a", "bundle_id": "bundle-1",
    "layout": "current",
    "supplied": {"generator_version": "spud 0.9.2", "commit_sha": "a" * 40},
})
limits = BundleLimits()
selected, limitations = resolve_artifacts(Path("/private/bundle"), descriptor, limits)
retained = read_bundle(Path("/private/bundle"), selected, limits, descriptor.expected_digests)
bundle = normalize_bundle(descriptor, retained, limitations)
receipt = AdmissionStore(Path("/private/admission")).admit(bundle)
```

## Supported layouts

| Role | Current layout | Legacy layout |
| --- | --- | --- |
| `graph` | `graphify-out/graph.json` | same |
| `graph_report` | `graphify-out/GRAPH_REPORT.md` | same |
| `citation_index` | `spud-out/json/analysis/inputs/graph-index.json` | same |
| `article` | `spud-out/markdown/**/*.md` | `spud-out/**/*.md`, excluding `spud-out/site/**` and `spud-out/json/**` |
| `okf_manifest` | `spud-out/manifest.yaml` | same |
| `run_manifest` | `run-manifest.yaml` | same |
| `source_evidence` | descriptor `source_binding.content_manifest_path` | same |
| `archive` | `explicit` selection only; retained as opaque bytes | same |

`layout: "auto"` refuses to choose when articles exist under both roots: it
raises `DescriptorError` with an ambiguity message instead of silently
preferring one. `layout: "explicit"` admits exactly the enumerated selection.

## Evidence grades

Grades record *how* evidence was produced and are never promoted.

| Grade | Record kinds | Source |
| --- | --- | --- |
| `recorded_artifact` | `graph_symbol`, `graph_relationship` | Graphify graph nodes and edges, with the producer's own `_origin`/`confidence` attribution |
| `recorded_citation` | `citation_entry` | SPUD's flat citation index; `relation` is always `null`, so a citation never becomes a relationship |
| `generated_narrative` | `narrative_passage` | Graph report and article text, inert, with half-open `[start_line, end_line)` locators |
| `retained_provenance` | `provenance_assertion` | OKF and run-manifest fields, retained as asserted, not verified, with half-open `[start_line, end_line)` locators; scalars the flat reader cannot represent faithfully, including double-quoted escape syntax, are skipped rather than altered |

Every record carries a `locator` naming the artifact path, its content digest
and either a JSON pointer or a line range, so any answer can be traced back to
retained bytes.

## Revision binding

| Value | Meaning |
| --- | --- |
| `unknown` | No commit identity was supplied or found in a retained manifest |
| `asserted` | A commit identity exists but was not verified against retained source evidence |
| `bound` | A supplied `source_binding` named the graph's verified digest and an exact snapshot, and it validated against retained source evidence |

`bound` requires `graph_digest`, `snapshot_id`, `commit_sha`,
`content_manifest_digest` and `content_manifest_path`; every graph source file
must be covered by the manifest, otherwise the bundle keeps the
`unbound_graph_source_files` limitation and stays `asserted` or `unknown`. The
retained manifest must itself name the same commit, otherwise the bundle keeps
the `unbound_commit_evidence` limitation: matching digests and paths never
establish a commit identity. A
bare `commit_sha` is always only `asserted`. Source coverage stays `unknown`
unless a verified binding supplies `complete` or `partial`.

## Limitation reasons

| Reason | Meaning |
| --- | --- |
| `missing_graph`, `missing_graph_report`, `missing_okf_manifest`, `missing_run_manifest`, `no_articles_selected` | A companion artifact was absent from the bundle |
| `malformed_graph_json`, `malformed_citation_index` | Bytes were retained but could not be parsed |
| `unsupported_graph_profile`, `unsupported_citation_profile`, `unsupported_artifact_format` | Retained bytes are outside `spud-reader/v1`'s understood shapes (archives included) |
| `undecodable_narrative_text` | Narrative bytes are not decodable text |
| `unknown_generator_version` | The caller supplied no usable producer version; a blank value is retained but not believed |
| `skipped_uploads` | A retained manifest reports skipped files |
| `unverified_source_binding`, `missing_bound_graph`, `unbound_graph_source_files`, `unbound_commit_evidence` | A supplied binding could not be verified against retained evidence |

Graph identities, labels, relations, citation labels and declared limitation
scopes must carry non-whitespace content: unusable retained fields keep their
bytes and surface an `invalid_graph_records` or `invalid_citation_records`
limitation, and an unusable descriptor scope is a `DescriptorError`.

Limitations are never repaired by inference. They appear in the receipt, in
`admission.limitations`, and as machine-readable `missing_evidence` entries
classified as `artifact`, `binding`, `coverage` or `provenance`. Declared
partial source coverage is reported as a `coverage` entry even when nothing
else is limited, so a bundle covering part of the repository never answers a
miss as absence.

## Admission store and receipts

`AdmissionStore` persists bytes, metadata and a recomputed receipt under a
hash-derived private directory tree (`0o700`), publishing each bundle with a
single atomic rename. The receipt digest covers the complete normalized
metadata, including record payloads, artifact roles and supplied provenance, so
an edit to retained metadata fails read-back verification. An exact retry of the same bundle returns the same
receipt; changed bytes, changed metadata or an added companion raises
`AdmissionConflict` and requires a new `bundle_id`. An interrupted admission is
never queryable, and a corrupted artifact raises `AdmissionValidationError` with
a digest mismatch on read-back rather than answering from damaged evidence.
`recover()` reclaims interrupted staging and unreferenced directories;
`damaged_bundles()` reports referenced bundles whose evidence cannot be read,
and `discard_damaged()` removes one so its `bundle_id` can be re-admitted.
Damage is never repaired by inference and a readable bundle is never discarded.

## Querying admitted artifacts

`ArtifactQueryService` answers bundle-scoped queries in the explicit
`knowitall.spud-artifacts/v1` envelope (`schemas/knowitall.spud-artifacts/v1/`,
examples in `examples/knowitall.spud-artifacts/v1/`).

| Query kind | Fields |
| --- | --- |
| `symbol` | `name`, `match`: `exact` or `normalized` |
| `relationships` | `symbol_id`, `direction`: `incoming` or `outgoing`, `relations` |
| `artifact_path` | `path` |
| `narrative_search` | `text` |

Each response names the resolved `bundle_id`, `receipt_digest`,
`reader_profile`, `revision_binding` and `bound_snapshot`, the admitted
artifacts with digests, source coverage and limitations. Status is explicit
(`ok`, `partial`, `not_found`, `unavailable`, `invalid_request`): a bundle with
any limitation, or declared partial source coverage, answers `partial`, so an
incomplete bundle can never be read as repository-wide absence. Pages are bounded at 50 records by default with a
visible `continuation` token bound to the bundle receipt, the selector, the
query and the page size; replaying a token against a different bundle, query or
page size is `invalid_request`, while paging with a fresh `request_id` per call
is supported.

## Safety limits

2000 artifacts per bundle, 8 MiB per artifact, 64 MiB per bundle, 50 records per
page, digests as `sha256:` plus 64 lowercase hex characters. Bundle roots,
admission stores and any real SPUD output stay private and outside Git.
