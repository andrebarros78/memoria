# F04 â€” Canonical Runtime Proof â€” 02/10/2026

**Status:** `F04_PROVEN / PROVEN_CURRENT / SHADOW`
**Gate:** `C4 = PROVEN`
**Package:** `memoria-permanente 0.32.0`
**Runtime:** `V5.5-PRIMARY`
**Release:** `MEMORIA_PERMANENTE_CANONICAL_1.0`
**COGNITIVE_MISSION_PROVEN:** `NÃƒO`

## Runtime and schema

- canonical APIs `8787` and `8790`: HEALTHY;
- migration count: `58`;
- migration head: `0058_cognitive_offline_consolidation`;
- four F04 tables use forced RLS;
- `memory_app` remains non-superuser, non-createdb, non-createrole, non-replication and non-bypassrls;
- V5.5 live runtime proof: PASS;
- V5.5 conformance compatible: `true`;
- restart/recovery continuity: `true`.

## C4 live proof

- manual consolidation: PASS;
- deterministic replay: PASS;
- durable checkpoint pipeline: PASS;
- forced interruption: expected exit `73` after 7 persisted stages;
- recovery after interruption: PASS;
- fencing token advanced and stale execution did not retain authority;
- canonical promotions: `0`;
- canonical memory snapshot hash before/after manual run: unchanged;
- canonical memory snapshot hash before/after recovery: unchanged;
- generated candidates remain `VALIDATED_SHADOW` or `REJECTED`;
- capture/retrieval dependency: `false`.

## Tests and quality

- F04 targeted suite: **17 passed, 0 failed**;
- full regression on release runtime: **406 passed, 2 skipped, 0 failed**;
- Ruff active canonical scope: **PASS**;
- compileall release package: **PASS**;
- `git diff --check`: **PASS**;
- known non-product issue: the project `.venv` also contains `windows-mcp 3.1.3`, whose optional dependencies are incomplete; it is not part of the MEMORIA-PERMANENTE dependency contract.

## Security

- live auth/security regression: **12/12 PASS**;
- forced RLS: PASS;
- tenant/scope isolation already proved in isolated and live F04 evidence;
- direct canonical promotion from consolidation: forbidden and observed count `0`;
- secrets exposed: `false`.

## Performance

- F04 is `OPTIONAL_ASYNC` and is not invoked from capture/retrieval request paths;
- recorded retrieval P95 during F04 benchmark: `576.6835 ms`;
- benchmark ceiling: `2000.0 ms`;
- canonical retrieval unchanged: `true`.

## Backup and recovery

- encrypted backup: **PASS**;
- backup id: `v52-20261002T174343Z-a23488c5`;
- cipher: `AES-256-GCM`;
- plaintext retained: `false`;
- authenticated manifest: `true`;
- encrypted restore drill: **PASS**;
- `pg_amcheck`: **PASS**;
- audit chain: `true` with `1819` events;
- migration head after restore: `0058` / 58 migrations;
- plaintext restore temp retained: `false`.

## Rollback

The authoritative rollback procedure is `docs/F04_ROLLBACK_PROCEDURE.md`. F04 remains SHADOW and never mutates canonical memory truth; disabling `COGNITIVE_CONSOLIDATION` removes the cognitive worker from operation without breaking capture/retrieval.

## Decision

All F04/C4 acceptance requirements applicable to Offline Consolidation are evidenced on the canonical Windows runtime. **F04 is closed as `F04_PROVEN`.** This does not pre-approve later gates and does not declare `COGNITIVE_MISSION_PROVEN`.
