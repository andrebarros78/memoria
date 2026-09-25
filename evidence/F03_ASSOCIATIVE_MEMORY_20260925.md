# F03 â€” Associative Memory / Spreading Activation â€” isolated proof

Status: **PASS (isolated reproducible proof; canonical deployment not yet claimed by this artifact).**

## Executive criteria exercised

- graph propagation: PASS;
- bounded traversal: PASS;
- scope isolation: PASS;
- deterministic trace: PASS;
- loop protection: PASS;
- conflict/evidence filter: PASS;
- canonical evidence sources: Ontology, ExperienceGraph and pgvector;
- precision benchmark: 1.000 (acceptance >= 0.80);
- recall benchmark: 1.000 (acceptance >= 0.75);
- restart in a fresh interpreter: PASS;
- direct runtime table write: BLOCKED;
- cross-tenant read/write: ISOLATED/BLOCKED;
- FORCE RLS tables: 2;
- canonical memory hashes unchanged: PASS;
- base retrieval selection unchanged: PASS.

## Performance

- baseline retrieval P95: 319.584400 ms;
- F03 shadow retrieval P95: 297.597500 ms;
- observed overhead: -6.879841%;
- acceptance ceiling: +20.0%.

The measurement is evidence for this run, not a general performance guarantee.

## Persistence and migration

- migration count: 57;
- migration head: `0057_cognitive_associative_memory`;
- persisted association candidates after restart: 4.

## Safety boundary

F03 remains `SHADOW`. Association candidates are derived accessibility signals, not canonical truth, and cannot silently change base retrieval ranking or promote knowledge.
