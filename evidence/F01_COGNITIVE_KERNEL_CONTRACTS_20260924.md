# F01 - Cognitive Kernel Contracts Evidence

## Executive source

Executed against `PROJETO_EXECUTIVO_MEMORIA_UNIVERSAL_COGNITIVA_ANALOGA_HUMANA-1 (1).md`.

F01 requires `cognitive_contracts.py`, `cognitive_types.py`, and `cognitive_policy.py` without changing existing behavior.

## Implemented contract surface

- cognitive contracts, scopes, signals and evaluations;
- proposed universal cognitive operations and event names as contract-only declarations;
- storage-port marker contracts without backend coupling;
- human automation and capability classes;
- all cognitive feature flags default OFF;
- F01 accepts SHADOW only;
- no direct truth mutation or knowledge promotion;
- fail-closed tenant/owner isolation;
- bounded identifiers, source refs, evidence refs and metadata cardinality;
- immutable metadata and policy trace after construction.

## Migration decision

No SQL migration was created in F01. Current migration head remains `0054_embedding_worker_role_login_normalization` and `git diff -- migrations` is empty.

This is deliberate: F01 explicitly must not change existing behavior, while the executive migration plan reserves `0055_cognitive_activation` for the Activation capability. See `docs/F01_SCHEMA_AND_MIGRATION_PLAN.md`.

## Tests

- F01 targeted/unit/security/integration/E2E/restart suite: **15 passed, 0 failed**.
- Full regression: **355 passed, 2 skipped, 0 failed**.
- Ruff: **PASS**.
- `git diff --check`: **PASS** before closure.
- One existing Starlette/AnyIO deprecation warning remains non-failing.

## E2E / restart / compatibility

A fresh Python interpreter:

1. imports the existing canonical API;
2. snapshots OpenAPI paths;
3. imports F01 cognitive contracts;
4. evaluates an allowed same-scope envelope;
5. rejects a cross-tenant envelope;
6. confirms OpenAPI paths are unchanged.

No `/v1/cognitive` route is exposed by F01.

## Benchmark

`evidence/F01_COGNITIVE_KERNEL_BENCHMARK_20260924.json` records 100,000 policy evaluations. Latest recorded run: approximately **132,162 operations/second**, **7.57 microseconds/operation**. This is a baseline measurement; the executive project defines no numeric F01 performance threshold.

## Persistence and recovery scope

F01 introduces no persisted cognitive state, worker, queue, API route or schema object. Therefore persistence/recovery proof for F01 is limited to restart/import equivalence and rollback isolation. Persisted activation state begins in the subsequent Activation phase.

## Rollback

Git-revert the F01 implementation/hardening commits. No database rollback is required because F01 changed no migration or database object.

## Decision

**F01_PROVEN** for the Cognitive Kernel Contracts phase only. This does not mean COGNITIVE_MISSION_PROVEN or terminal MISSION_PROVEN.
