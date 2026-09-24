# F01 - Cognitive Kernel Contracts

Status: implemented, hardened, regression-validated and isolated from existing behavior.

## Scope

F01 introduces the cognitive kernel contract surface only. It does not enable cognitive behavior, mutate memory truth, promote knowledge, expose `/v1/cognitive` routes, create workers, alter retrieval ranking, or change database schema.

## Modules

- `src/memory_permanent/cognitive_contracts.py`: universal cognitive envelope, scopes, proposed operations/events, default-OFF feature flags, and storage-port marker contracts.
- `src/memory_permanent/cognitive_types.py`: bounded score, cognitive states/relations, human automation levels and capability classes.
- `src/memory_permanent/cognitive_policy.py`: fail-closed F01 policy boundary.

## Security invariants

- default and only F01 execution mode: `SHADOW`;
- every cognitive feature flag defaults OFF;
- no direct mutation authority;
- no direct promotion;
- tenant and owner scope binding is mandatory;
- cross-scope requests fail closed;
- only explicit cognition capabilities are accepted;
- identifiers, source refs, evidence cardinality and attribute cardinality are bounded;
- contract metadata and policy traces are immutable after construction;
- outputs prove no truth mutation/promotion;
- cognitive layer can be absent/disabled without changing V5.5 core behavior.

## Integration / E2E / restart

A fresh Python interpreter imports the canonical API, snapshots its route contract, imports and evaluates F01 contracts, verifies cross-scope denial, and proves the API route contract is unchanged. No `/v1/cognitive` route is published in F01.

## Migration

See `docs/F01_SCHEMA_AND_MIGRATION_PLAN.md`. F01 intentionally performs no DB migration; `0055` remains reserved for cognitive activation.

## Benchmark

`scripts/benchmark_f01_cognitive_contracts.py` measures policy-evaluation overhead as a baseline only. The executive project defines no numeric F01 performance threshold.

## Rollback

Revert the F01 commits or remove the F01 modules/tests/docs/benchmark. No schema migration, API route, database object, runtime worker, or persisted cognitive state must be reversed.
