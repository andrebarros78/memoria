# F03 — CANONICAL RUNTIME PROOF

**Status:** `PROVEN_CURRENT / SHADOW`

- Package: `0.31.0`
- Implementation head: `e94a9d524a2452e93aca8030d939fccd8e09c49c`
- Wheel SHA-256: `2d8687f0304a86f6643a57c0c6313d8d6bbafbc464f891ea48a3cea34d574b7f`
- Database: 57 migrations, head `0057_cognitive_associative_memory`
- C0–C3: `PROVEN`; C4–C12: `OPEN`
- Regression: `389 passed, 2 skipped`; Ruff `PASS`; diff-check `PASS`
- Live F03: both `8787` and `8790` produced bounded PGVector associative candidates with `1000 ms` budget after restart validation
- F03 storage: FORCE RLS; `memory_app` direct grants limited to SELECT; direct cognitive writes and cross-tenant access blocked in dedicated proof
- Terminal backup: `v52-20260925T151925Z-1a50055f`, AES-256-GCM, plaintext not retained
- Recovery: `PASS`; pg_amcheck `PASS`; audit chain `1728` events; erasure replay `PASS`; head `0057`
- Retrieval remains authoritative; associative candidates stay derived and SHADOW-only
- `COGNITIVE_MISSION_PROVEN = NÃO` because C4–C12 remain open

Next scope: **F04 — Offline Consolidation**.
