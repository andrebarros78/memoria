# V5.3 Deep Architecture Correction Proof - 2026-09-05

## Scope
Canonical project only: `C:\New Projet\MEMORIA-PERMANENTE`.

## Baseline
- Branch: `v5.3-primary-20260904`
- Previous HEAD: `389cb4013c56e8a0b96a316f0aa88de18a763ccf`
- Release: `0.28.0`
- Canonical migrations: 46

## Corrections applied
1. Removed UTF-8 BOM from tracked Python sources where it interfered with external AST/tooling interoperability.
2. Repaired proven mojibake in `store.py` without changing valid UTF-8 Portuguese text.
3. Added public `PostgresMemoryStore.connection()` transactional boundary with tenant/access context; runtime domain modules no longer depend on private `store._connection()`.
4. Added structured exception logging to fail-safe governance/lifecycle fallbacks and conversation retry failures.
5. Removed runtime worker password extraction from pgpass; workers use `PGPASSFILE` plus passwordless DSN.
6. Canonical runtime worker launcher pins V5.3 runtime/database identity.
7. Recovery launchers delegate to canonical V5.3 startup and validate canonical identity.
8. Database bootstrap keeps runtime role `memory_app` non-owner/non-privileged.
9. Added HTTP defense-in-depth headers: CSP, no-sniff, frame deny, no-referrer, permissions policy, COOP/CORP, no-store.
10. Added regression contracts in `tests/test_deep_architecture_hardening.py`.

## Verification
- Full pytest: 269 passed, 2 skipped (POSIX-only), 0 failed.
- Focused architecture/API tests: 23 passed.
- mypy: 0 issues in 47 source files.
- Ruff: 0 issues for src/tests and hardened runtime workers.
- Bandit: 0 findings.
- `git diff --check`: PASS.
- `pip-audit --local`: rc=0; local unpublished package skipped, no vulnerable dependency reported.
- Release wheel: clean=true, 46/46 migrations, required assets/DNA present, forbidden entries=0.
- Wheel SHA-256: `38d4aaccc9627f59f64aaf3ddb4554fffa957928c792b43bec2ad62cd6f47f0e`.
- Isolated encrypted restore: PASS.
- Restore migration count: 46.
- pg_amcheck: PASS.
- Restored audit chain: PASS, 222 events.
- Erasure replay: PASS.
- Restored runtime role: `memory_app`, privileged=false.
- PostgreSQL 18.6 / pgvector 0.8.6.
- Production runtime preflight: READY.
- Production health: HTTP 200, V5.3-PRIMARY, release channel v5.3-primary-promoted.
- Unauthenticated `/v1/memories`: HTTP 401.
- Security response headers verified live.

## Result
The correction set is operationally validated with regression, static analysis, packaging, recovery, privilege, authorization, and live-runtime evidence.