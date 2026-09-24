# F01 â€” Cognitive Kernel Contracts Evidence

F01 implements only the contract/type/policy foundation required before activation, priming, salience or other cognitive engines are introduced.

## Objective evidence
- Target suite: 8 passed, 0 failed.
- Full regression after F01: 348 passed, 2 skipped, 0 failed.
- Ruff: PASS after correcting 9 formatting/modernization findings and retesting.
- Existing V5.5 behavior: unchanged; no API route, DB schema, migration, worker or retrieval ranking changed.
- Security: SHADOW-only; cross-tenant/cross-owner denied; unauthorized capability denied; direct mutation/promotion forbidden.
- Persistence/restart impact: none introduced in F01 because this phase creates immutable in-process contracts only and intentionally introduces no persisted cognitive state. Persistence begins with later engines/migrations.
- Recovery: rollback is removal of isolated F01 modules/tests/docs; no database rollback required.

## Acceptance
The F01 specification requires `cognitive_contracts.py`, `cognitive_types.py`, and `cognitive_policy.py` without changing existing behavior. Those artifacts exist and are covered by targeted and full regression tests.
