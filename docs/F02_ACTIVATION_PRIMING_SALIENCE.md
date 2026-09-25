# F02 â€” Activation + Priming + Salience

Status: implemented and isolated-proof validated; promotion requires canonical runtime deployment proof.

## Architectural role

F02 adds cognitive accessibility signals without changing memory truth. Activation, priming, interference and salience are separate from canonical memory content and cannot promote facts or rewrite validated content.

## Runtime mode

The only enabled integration path for F02 is `SHADOW`: compute and persist cognitive observations after canonical operations while leaving the canonical ranking/decision authoritative. Feature flags default OFF and may be enabled independently.

## Modules

- `cognitive_activation.py`
- `priming_policy.py`
- `interference_policy.py`
- `activation_trace.py`
- `salience_engine.py`
- `salience_policy.py`
- `salience_explanation.py`
- `cognitive_observability.py`

## Schema

- `0055_cognitive_activation.sql`: activation state/events, priming edges, interference events, FORCE RLS, controlled runtime functions and least privilege.
- `0056_cognitive_salience.sql`: append-only salience observations, FORCE RLS and controlled runtime function.

## Security invariants

- cross-tenant priming forbidden;
- tenant context required;
- runtime role cannot directly mutate cognitive tables;
- consumer input cannot set final salience;
- source trust and priming budgets are bounded;
- cognitive failures fail open only toward the already-authorized canonical read/capture result, never toward an unauthorized cognitive mutation;
- canonical memory hash/truth is not changed by shadow cognition.

## Acceptance

C1/C2 require deterministic bounded scoring, decay/trace, no scope leak, restart persistence, explainable salience and abuse tests. Isolated proof evidence is under `evidence/F02_COGNITIVE_ACTIVATION_SALIENCE_20260925.*`; canonical-runtime promotion is recorded separately after deployment.

## Rollback

Disable the three cognitive feature flags and restart first. Schema removal, if ever required, must be performed by a new reviewed rollback migration in reverse dependency order; never rewrite applied migration files.
