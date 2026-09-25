# F02 â€” Activation + Priming + Salience â€” Isolated Shadow Proof

Status: **PROVEN_ISOLATED_SHADOW_NOT_YET_PROMOTED**.

## Implemented

- Cognitive Activation Engine with bounded deterministic components and trace.
- Priming policy with source trust, scope, budget, TTL and activation caps.
- Interference/habituation bounded penalties.
- Functional salience with objective bounded dimensions; no consumer-assigned final score.
- Async shadow observer integrated after canonical capture/retrieval, without reranking.
- Feature flags default OFF.
- Migrations `0055_cognitive_activation` and `0056_cognitive_salience`.
- Forced RLS and least-privilege database functions for runtime writes.
- Cognitive metrics without memory-content exposure.

## Proof executed 25/09/2026

- F02 isolated runtime proof: **PASS**.
- Migration head: `0056_cognitive_salience` / 56 migrations.
- Activation persisted: `True`.
- Priming persisted: `True`.
- Salience persisted: `True`.
- Restart in a fresh interpreter: `True`.
- Direct runtime-table writes blocked: `True`.
- Cross-tenant read isolated: `True`.
- Cross-tenant write blocked: `True`.
- Forced-RLS cognitive tables: `5`.
- Canonical memory hash unchanged: `True`.
- Shadow dispatcher failures/drops: `0 / 0`.
- Temporary proof databases remaining after cleanup: `0`.

## Verification

- Targeted cognitive suite: **34 passed, 0 failed**.
- Full worktree regression: **374 passed, 2 skipped, 0 failed**.
- Ruff on active canonical code (`src tests scripts`): **PASS**.
- Repository-wide Ruff is not used as the F02 gate because three tracked historical/repair Python files outside the active scope contain pre-existing import-order findings.
- `git diff --check`: **PASS**.

## Benchmark

- Baseline retrieval P95: `320.6248 ms`.
- Shadow retrieval P95: `242.0861 ms`.
- Measured P95 overhead: `-24.4955%`.
- Acceptance ceiling: `+20.0%`.

The measured run is evidence of this execution, not a general latency guarantee.

## Rollback

1. Disable `COGNITIVE_ACTIVATION`, `COGNITIVE_PRIMING`, and `COGNITIVE_SALIENCE` (all default OFF).
2. Restart the affected API process; canonical V5.5 capture/retrieval remains authoritative.
3. If schema rollback is required before any later cognitive migration depends on these objects, remove `0056` objects first and then `0055` objects using a reviewed rollback migration. Never edit already-applied migration history in place.
4. Reinstall the preceding proven wheel/commit if code rollback is required.
5. Re-run V5.5 health, full regression, security regression, restart and recovery proofs.

## Promotion boundary

This evidence proves F02 in an isolated database and SHADOW integration. It does **not** by itself prove deployment in the currently running canonical API or `COGNITIVE_MISSION_PROVEN`.
