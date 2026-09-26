# F04 — Offline Cognitive Consolidation

**State before canonical promotion:** implementation/proof candidate
**Capability class:** `OPTIONAL_ASYNC`
**Mode:** `SHADOW`
**Feature flag:** `COGNITIVE_CONSOLIDATION` (default OFF)

## Objective

Consolidate repeated/high-value memory evidence outside capture/retrieval request paths. F04 may create derived candidates and execution evidence, but it does not mutate canonical memory truth and does not promote a candidate into a fact, decision, learning or generalized concept.

## Pipeline

`SELECT → REPLAY → COMPARE → CLUSTER → ASSOCIATE → DETECT_PATTERN → GENERATE_CANDIDATE → VALIDATE → CONSOLIDATE → RECORD_PROVENANCE`

Every stage produces a durable checkpoint. Recovery resumes from a persisted source set and replays deterministic digests before completion.

## Scheduler and worker

The scheduler is a portable one-shot policy layer rather than a host-specific cron implementation. Windows Task Scheduler, systemd timers, Kubernetes CronJobs or a manual operator may invoke the worker without changing the cognitive contract.

Execution requires:

- healthy database;
- healthy operational queue;
- no incompatible recovery in progress;
- available I/O budget;
- CPU below policy threshold;
- mode-specific trigger conditions;
- exclusive lease per scope with fencing token.

The worker uses a dedicated agent identity. A stale/foreign/expired fencing token is rejected at the database boundary.

## False-consolidation controls

- minimum sample size;
- proof reference for every source memory;
- explicit conflict analysis;
- bounded confidence threshold;
- candidate-only state (`VALIDATED_SHADOW` or `REJECTED`);
- deterministic replay digests;
- no direct canonical promotion;
- rollback by disabling `COGNITIVE_CONSOLIDATION` and ignoring derived F04 state.

## Persistence

Migration `0058_cognitive_offline_consolidation` adds:

- `cognitive_consolidation_runs`;
- `cognitive_consolidation_checkpoints`;
- `cognitive_consolidation_candidates`;
- `cognitive_consolidation_events`.

All four tables use forced RLS. Checkpoints, candidates and events are append-only. `memory_app` receives SELECT access to F04 tables and EXECUTE access only to governed `SECURITY DEFINER` functions; direct DML is revoked. Source composition occurs through `memory_consolidation_source_snapshot`, which returns metadata/digests/signals after tenant/scope filtering and does not expose memory content.

## Gate C4 proof requirements

C4 is promotable only after all of these pass:

- idle consolidation run;
- deterministic replay;
- durable checkpoints;
- forced worker interruption with persisted progress;
- recovery after interruption using a new fencing token;
- rejection of stale fencing token;
- scope/tenant isolation;
- restart persistence;
- recovery/restore proof;
- full regression and security conformance;
- no capture/retrieval regression.

Isolated evidence: `evidence/F04_OFFLINE_CONSOLIDATION_20260926.json` and `.md`.
