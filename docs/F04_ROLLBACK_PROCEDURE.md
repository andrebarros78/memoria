# F04 — Rollback Procedure

## Scope

This procedure rolls back **Offline Cognitive Consolidation** without altering canonical memory truth.

## Immediate containment

1. Set `COGNITIVE_CONSOLIDATION=0` for all runtime processes.
2. Stop only the consolidation worker/scheduler process. Do not stop PostgreSQL or the canonical capture/retrieval APIs unless a separate runtime incident requires it.
3. Confirm `/health` remains healthy and canonical capture/retrieval still operate.

## Code rollback

If the F04 package itself must be reverted, reinstall the preceding proven F03 release (`0.31.0`) from its authenticated release artifact, then restart the affected API/worker processes and rerun V5.5 health, security, regression and recovery proofs.

## Schema rollback

Do **not** edit or delete the already-applied `0058_cognitive_offline_consolidation` migration from migration history.

If physical schema reversal is required before any later migration depends on F04 objects, use one of these governed paths:

- a reviewed forward/reverse migration that removes F04 objects in dependency-safe order; or
- restore the authenticated encrypted pre-change backup, followed by migration verification, erasure replay, integrity/audit verification and runtime preflight.

## Data semantics

F04-derived candidates are `VALIDATED_SHADOW` or `REJECTED`; they do not directly mutate canonical memory truth. Rollback therefore disables or removes derived consolidation state, not source memories.

## Post-rollback proof

Require all of the following before considering rollback complete:

- package/runtime identity matches the intended prior release;
- migration state is internally consistent;
- canonical APIs healthy;
- capture/retrieval regression passes;
- security regression passes;
- backup/restore validation passes;
- no orphan lease remains;
- no canonical memory hash changed because of the rollback;
- Git working tree/evidence chain is reconciled.
