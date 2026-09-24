# F01 â€” Cognitive Kernel Contracts

Status: implemented and regression-validated.

## Scope
F01 introduces the cognitive kernel contract surface only. It does not enable cognitive behavior, mutate memory truth, promote knowledge, or change retrieval ranking.

## Modules
- `src/memory_permanent/cognitive_contracts.py`: universal cognitive envelope, scope, signal and evaluation contracts.
- `src/memory_permanent/cognitive_types.py`: bounded score and canonical cognitive state/relation types.
- `src/memory_permanent/cognitive_policy.py`: fail-closed F01 policy boundary.

## Security invariants
- default and only F01 execution mode: `SHADOW`;
- no direct mutation authority;
- no direct promotion;
- tenant and owner scope binding is mandatory;
- cross-scope requests fail closed;
- only explicit cognition capabilities are accepted;
- outputs carry deterministic trace fields proving no truth mutation/promotion;
- cognitive layer can remain disabled without changing V5.5 core behavior.

## Rollback
Remove the three F01 modules and their tests. No schema migration, API route, database object, runtime worker, or existing core behavior was changed by F01.
