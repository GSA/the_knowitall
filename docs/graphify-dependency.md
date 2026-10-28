# Graphify dependency record

Knowitall's first extractor adapter targets the following immutable artifact:

- Distribution: `graphifyy` 0.9.96
- Wheel: `graphifyy-0.9.96-py3-none-any.whl`
- Wheel SHA-256: `bbef4c79b5905f45e384a7ca49417cd6c131d4774f280037159dd6cf4c425e29`
- Source distribution SHA-256: `3e1938a78e01475d5931187896c8d6ab17b04f30db06e271c86bd9f50f946fc6`
- Source revision: `dac063456bc1f5d92354ec3936fd9dd1513a83f3`
- Source archive SHA-256: `4dc2e136ab13ba1885fc28ac8a0a3cb253ead641ecbb1e059dc136e0d5723e0a`
- Package metadata license expression: `Apache-2.0`
- Included notices: `LICENSE` (Apache-2.0), `LICENSE-MIT`, and `NOTICE`
- Python metadata compatibility: `Requires-Python >=3.10`; the Knowitall floor is Python 3.12.
- Acceptance runtime observed on Python 3.14: `tree-sitter` 0.25.2, `tree-sitter-python` 0.25.0, and `tree-sitter-typescript` 0.23.2 (plus the distribution's remaining declared base dependencies).

The 0.9.96 source distribution's `graphify/` tree, `pyproject.toml`, and all three license/notice files were compared with the recorded source revision: 237 files matched byte-for-byte, with no missing or mismatched files. The source revision declares version 0.9.96. This verifies package-to-source correspondence for the adopted artifact; it does not authorize copying Graphify source into this repository.

The adapter invokes an explicitly configured executable without a shell, using only an allowlisted environment, confined source/output paths, and the package-defined `--code-only` local-AST/no-API argument. The intended normalized invocation is:

```text
graphify extract <immutable-source> --out <staging-output> --code-only --no-cluster
```

No API/model credentials, proxy variables, user configuration, hooks, or network-enrichment options are inherited. Exit zero is only a subprocess receipt; Knowitall separately validates artifact JSON, source binding, locators, endpoints, digests, provenance, and coverage before publication eligibility.
