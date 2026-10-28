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
- Acceptance runtime observed on CPython 3.14/Linux x86_64: all 31 exact distributions and wheel hashes recorded in `requirements/graphify.lock`.

The lock is the complete accepted runtime closure, not just the top-level package. It was generated from concrete wheel bytes and verified by an offline `pip install --no-index --require-hashes --no-deps`. Because several wheels are platform-specific, this lock intentionally applies only to CPython 3.14 on compatible Linux x86_64 systems; another platform requires a separately reviewed complete lock.

The 0.9.96 source distribution's `graphify/` tree, `pyproject.toml`, and all three license/notice files were compared with the recorded source revision: 237 files matched byte-for-byte, with no missing or mismatched files. The source revision declares version 0.9.96. This verifies package-to-source correspondence for the adopted artifact; it does not authorize copying Graphify source into this repository.

The adapter invokes an explicitly configured executable without a shell, using only an allowlisted environment, confined source/output paths, and the package-defined `--code-only` local-AST/no-API argument. The intended normalized invocation is:

```text
graphify extract <immutable-source> --out <staging-output> --code-only --no-cluster
```

No API/model credentials, proxy variables, user configuration, hooks, or network-enrichment options are inherited. `GraphifyConfig.executable` is a Python interpreter file inside a dedicated virtual environment built from the lock, and every process starts with `-I -S` so user/system site packages and startup hooks cannot run. The adapter admits exactly one package root, approves the interpreter by SHA-256, and probes the running runtime for Python and all 31 exact distribution versions plus a `graphify` import origin inside that root before extraction. A mismatch fails closed.

Exit zero is only a subprocess receipt; Knowitall separately validates artifact JSON, source binding, locators, endpoints, digests, provenance, and coverage before publication eligibility.

## Runtime integrity scope

This slice verifies *package and version identity* of a locally constructed, lock-built runtime for synthetic conformance. It does not attest the host operating system, the ELF loader, system shared libraries, or filesystem immutability, and it makes no production runtime-integrity claim. Production execution requires a deployment-attested immutable runtime image; that boundary is tracked separately and must be designed with the owning deployment product rather than inferred here.
