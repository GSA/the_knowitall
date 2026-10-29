# Current state

`regc` implementation and conformance/documentation are committed through
`940103f`. Native branch review job 326 (range d5ab267..0c2f5cd) is queued behind
shared daemon work; the subsequent malformed-pointer fix needs review coverage
before PR delivery. Kata remains open; push/PR and plan cleanup await review.
Latest completed full run: 160 passed with real pinned Python/TypeScript extraction enabled.
Contract examples, wheel/sdist (private-state exclusion), compileall and diff
checks pass. Real partial-coverage and spawned-process extraction-death tests pass.

Requests retain exact source bytes and identities; checkpoints validate native
artifacts and Graphify companions; predecessor-conditional publication preserves
historical retry receipts and never reselects an older completed request.
Incomplete inventory blocks without deletion. Valid exclusions publish explicit
partial evidence. Fatal extraction remains retryable and does not advance current.

Follow-up `the_knowitall#88nk` owns qualified unresolved-reference placeholders:
Graphify may emit sourceless non-AST targets for removed still-called symbols;
these artifacts are rejected while prior current evidence remains selected.
`the_knowitall#d2qt` owns deployment-provided runtime attestation.

Concurrent `.kata.toml` project-name rename remains outside this task's commits.
