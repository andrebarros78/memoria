# F01 Schema and Migration Decision

## Source constraints

F01 is the Cognitive Kernel Contracts phase and must not change existing behavior. The executive project also reserves the next database migration sequence, beginning at `0055_cognitive_activation`, for the activation capability implemented after F01.

## Decision

F01 has **NO DATABASE SCHEMA MIGRATION**.

Creating an empty or unrelated `0055` migration in F01 would consume the number explicitly planned for cognitive activation without providing a schema capability, and would contradict the F01 no-behavior-change constraint.

The migration deliverable for F01 is therefore this explicit migration-impact decision and the verified migration plan:

- current head remains `0054_embedding_worker_role_login_normalization`;
- no database object is created, changed, or removed by F01;
- `0055` remains reserved for the real activation-state schema when F02 implements Activation/Priming;
- rollback requires no database action.

This is a deliberate N/A resolution of the generic per-phase migration checklist, not an omitted migration.
