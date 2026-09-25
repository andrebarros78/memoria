# F03 â€” Associative Memory / Spreading Activation

Status: implemented and isolated-proof validated. Canonical production promotion requires the live deployment proof.

## Objective

A retrieved seed memory may activate related memories without an explicit query. F03 derives associations from existing canonical evidence and never turns an inferred association into memory truth.

## Canonical evidence sources

- Ontology / `memory_knowledge_relations`;
- ExperienceGraph / bound graph nodes and edges;
- pgvector / current-version embedding similarity.

## Pipeline

`seed -> neighbors -> relation weight -> hop decay -> scope filter -> conflict/evidence filter -> bounded associative candidates`.

## Hard limits

- maximum depth: 4 (default 2);
- node budget: max 256 (default 64);
- time budget: max 1000 ms (default 500 ms);
- candidate budget: max 128 (default 32);
- path loop protection;
- deterministic trace;
- fail-closed tenant/scope persistence.

## Modules

- `association_policy.py`;
- `associative_memory.py`;
- `spreading_activation.py`;
- migration `0057_cognitive_associative_memory.sql`.

## Integration rule

The ContextEngine returns the pre-existing lexical/semantic/state selection. F03 executes asynchronously after that selection and records only shadow traversal/candidate state. Association failure is contained inside the cognitive shadow failure domain.

## Rollback

1. disable `COGNITIVE_ASSOCIATION`;
2. restart runtime and prove V5.5/F02 behavior;
3. restore the prior release wheel if code rollback is needed;
4. keep additive `0057` tables inert, or restore the pre-deploy encrypted backup if exact schema rollback is required.
