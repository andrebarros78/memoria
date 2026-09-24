# V5.3 Final Hardening Audit Proof â€” 2026-09-05

## Scope

Canonical donor project only: `C:\New Projet\MEMORIA-PERMANENTE`.

This proof does not govern, synchronize, validate, or depend on any previously donated clean copy in another product.

## Baseline

- Branch: `v5.3-primary-20260904`
- Baseline before corrections: `49dd623bb619d78d91ca94d55771d7c32fff2adb`
- Package version: `0.28.0`
- Canonical migrations: 46 (`0001_base` through `0046_ai_integration_runtime_privileges`)

## Corrected gaps

1. Repaired UTF-8/mojibake corruption in tracked documentation, evidence, scripts and UI assets.
2. Removed hard-coded migration count from release packaging and made the contract derive the expected count from canonical migration files.
3. Corrected release verifier contradiction that rejected the required canonical `0008_governor_contract.sql` migration.
4. Eliminated static typing defects across the source package; platform key-provider protocol now models `protect_existing` explicitly.
5. Hardened temporal, durable-state, persistence and metric type narrowing.
6. Replaced the AI-integration suggestion dynamic SQL f-string with psycopg SQL composition while keeping all caller values parameterized and clause fragments code literals.
7. Hardened quality gates with repository-owned Ruff configuration and documented framework/fail-safe exceptions.
8. Removed Bandit medium SQL finding and documented three B105 false positives as non-credential policy/result/metric values.
9. Installed the audited wheel into the isolated API runtime so it no longer depends solely on launch-time source-path availability.
10. Revalidated the V5.3 runtime through the official preflight/start path.

## Objective validation

- Python compile: PASS.
- `ruff check src/memory_permanent tests`: PASS, 0 issues.
- `mypy src/memory_permanent --ignore-missing-imports`: PASS, 47 source files, 0 issues.
- `bandit -q -r src/memory_permanent`: PASS, 0 findings.
- Pytest: PASS â€” 262 passed, 2 POSIX-only skips, 0 failed. One third-party Starlette/AnyIO deprecation warning remains non-blocking.
- `pip-audit --local`: PASS for installed third-party dependencies; the local unpublished `memoria-permanente` package itself is not resolvable on PyPI and is therefore skipped by pip-audit.
- `git diff --check`: PASS.
- Strict UTF-8 corruption signature scan over tracked files: 0 findings.
- Dynamic SQL safety contract: PASS.

## Release proof

Built wheel: `memoria_permanente-0.28.0-py3-none-any.whl`

- SHA-256: `b1a7f22d215f0f8bfdf6b900f0fc5bce12e8011ae8d75a246c67fe6cc681a667`
- Entries: 101
- Canonical migrations packaged: 46 / 46
- Product DNA files: 1
- Required static assets: present
- Forbidden runtime/backups/key material: 0 entries
- Release verifier: `clean=true`

## Recovery proof

A real encrypted backup was restored into the isolated test database `memoria_permanente_v52_restoreproof`, never over the operational database.

Result: PASS.

- Backup id: `v52-20260905T023404Z-9e2c87a8`
- PostgreSQL: 18.6
- pgvector: 0.8.6
- `pg_amcheck`: PASS
- 46 migrations applied/verified
- Runtime role: `memory_app`
- Runtime role privileged: false
- Runtime preflight: READY
- Audit chain: valid, 222 events verified
- Erasure replay: PASS; external ledger verified
- Plaintext restore temporary retained: false
- Secret material exposed: false
- Recovery flow: `RESTORE -> MIGRATE -> ERASURE_REPLAY -> VERIFY`

## Runtime proof

Official V5.3 launcher preflight after deployment:

- Database role: `memory_app`
- Privileged database role: false
- Latest migration: `0046_ai_integration_runtime_privileges`
- Migration count: 46
- Runtime preflight: READY
- API: `http://127.0.0.1:8787/health` = HTTP 200
- Service: `MEMORIA-PERMANENTE`
- Version: `0.28.0`
- Runtime profile: `V5.3-PRIMARY`
- Release channel: `v5.3-primary-promoted`
- Direct purge enabled: false

## Terminal gate

The corrected V5.3 source, release packaging, isolated recovery path, database least-privilege preflight and active API runtime all passed their objective gates. Final Git commit and clean-baseline verification are the terminal consolidation steps for this audit.