# F02 — Canonical Runtime Proof — 25/09/2026

**Status:** `F02 = PROVEN_CURRENT / SHADOW`
**Package:** `memoria-permanente 0.30.0`
**Runtime:** `V5.5-PRIMARY`
**Release:** `MEMORIA_PERMANENTE_CANONICAL_1.0`
**COGNITIVE_MISSION_PROVEN:** `NÃO`

## Evidence

- implementation commit: `3327b4e68a7b056a2b39aa20d8413b62c3b5c460`;
- release/version commit: `49a774c`;
- wheel: `memoria_permanente-0.30.0-py3-none-any.whl`;
- wheel SHA-256: `dc9a18e850523614fbadfe0a4dc68d533bae6225fc3b9e7d27a8127c7771c1b1`;
- migrations: `56`, head `0056_cognitive_salience`;
- `0055_cognitive_activation` and `0056_cognitive_salience` applied to the canonical primary database;
- FORCE RLS: `5` cognitive tables;
- isolated F02 proof: `PASS`;
- full regression: `374 passed`, `2 skipped`, `0 failed`;
- cognitive targeted: `34 passed`; version-affected targeted: `46 passed`;
- Ruff active canonical scope: `PASS`; `git diff --check`: `PASS`; compileall: `PASS`;
- canonical APIs `8787` and `8790`: healthy after rolling restart;
- package observed after promotion: `0.30.0`;
- V5.5 conformance: `PASS`; restart/recovery continuity: `true`;
- live F02 hook on `8787`: activation and salience persisted;
- pre-upgrade cognitive state survived package replacement and restart;
- live security regression: `12/12 PASS`;
- pre-deploy encrypted backup: `v52-20260925T123044Z-7f1790e4`;
- post-deploy encrypted backup: `v52-20260925T125140Z-66b79710`;
- restore drill: `PASS`, `pg_amcheck=PASS`, audit chain valid with `1636` events, erasure replay `PASS`;
- no plaintext backup retained and no secret material exposed.

## Cognitive behavior proved

Activation, priming, interference and functional salience operate only as governed `SHADOW` cognition. The canonical capture/retrieval result remains authoritative. Activation does not change memory truth, and salience cannot promote an unproved claim into fact.

The isolated benchmark measured retrieval P95 `320.6248 ms` without the observer and `242.0861 ms` with F02 SHADOW in that run, an observed overhead of `-24.495516%` against the acceptance ceiling of `+20%`. This measurement is evidence of that execution, not a general latency guarantee.

## Security evidence

During canary proof development, priming attempted without the memory's project access context was rejected by PostgreSQL. The proof was then corrected to use the real access context and passed. This is evidence that the scope boundary denied the invalid access rather than a bypass.

## Rollback

1. Disable `COGNITIVE_ACTIVATION`, `COGNITIVE_PRIMING`, and `COGNITIVE_SALIENCE`; restart rolling.
2. If code rollback is required, reinstall `memoria_permanente-0.29.3-py3-none-any.whl`, SHA-256 `bb7e7a5ab0d0116706cf4f293f31c42eb53592cb239c3c97a3b14227272f29cc`.
3. Never edit applied migration history. For schema reversal use a reviewed reverse migration, or restore the authenticated pre-deploy backup.
4. Re-run health, V5.5 conformance, security, restart and recovery proofs.

## Gate state

`C0=PROVEN`, `C1=PROVEN`, `C2=PROVEN`. `C3–C12=OPEN`.

The recovery proof executed for F02 closes recovery evidence for this phase; it does not pre-approve terminal gate C10, which must be repeated over the complete cognitive architecture.

Therefore F02 is closed, but the complete Memória Universal Cognitiva is not yet terminally proven.
