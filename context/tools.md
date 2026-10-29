# Tools

Use native `kata show regc`, `kata claim`, `kata comment`, and `kata close` with
repository `.kata.toml`. Search before creating follow-ups; relate and register
worked tasks with Forge. Use native `roborev review --branch --wait` before PRs.

Verification uses isolated test dependencies and the complete CPython 3.14/Linux
Graphify lock runtime described in `docs/graphify-dependency.md`:

```sh
export PYTHONPATH="/absolute/path/to/test-dependencies:$PWD/src"
export KNOWITALL_GRAPHIFY_RUNTIME="/absolute/path/to/pinned-graphify-venv"
python3 scripts/check-contract-examples.py
python3 -m pytest -q
python3 -m build
python3 -m compileall -q src tests scripts
git diff --check
```

`UpdateLedger` retains immutable request manifests/bytes; `UpdateRunner.submit`
binds runtime/config before acknowledgment, `inspect` reports durable progress,
and `resume` restores a safe workspace and conditionally publishes. See
`docs/local-provider.md` for the Python API and cleanup policy. Store locks require
POSIX flock and local filesystem rename/fsync semantics, with one ledger per store.
