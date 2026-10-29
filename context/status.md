# Current state

`regc` implementation and recovery fixes are committed through `321ef02`.
Native branch review job 359 passes with no findings. Final verification:
181 tests passed with real pinned Python/TypeScript extraction enabled.
Recovered request, generation, pointer, receipt and initialization directory
renames are persisted before acknowledgment or successor selection. Missing
selected evidence fails closed; explicit unpublished-intent resubmission is safe.
Forge PR delivery follows the verified branch review.
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
