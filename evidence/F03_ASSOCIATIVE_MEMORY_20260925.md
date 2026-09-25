# F03 â€” Associative Memory / Spreading Activation â€” isolated proof

Status: **PASS (hardened isolated reproducible proof; canonical deployment is proven separately).**

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

## Hard budget semantics

Runtime default time budget is **500 ms**; the multi-source proof uses **1000 ms** to make the deterministic benchmark insensitive to host jitter. If the wall-clock budget expires, F03 fails closed with `FAIL_CLOSED_NO_PARTIAL_CANDIDATES`: partial timing-dependent candidates are discarded and the timeout trace is deterministic.

## Performance

- baseline retrieval P95: 401.532900 ms;
- F03 shadow retrieval P95: 351.043200 ms;
- observed overhead: -12.574237%;
- acceptance ceiling: +20.0%;
- complete multi-source traversal: 475.713400 ms under the 1000 ms proof budget.

The measurements are evidence for this run, not a general performance guarantee.

## Persistence and migration

- migration count: 57;
- migration head: `0057_cognitive_associative_memory`;
- persisted association candidates after restart: 4.

## Safety boundary

F03 remains `SHADOW`. Association candidates are derived accessibility signals, not canonical truth, and cannot silently change base retrieval ranking or promote knowledge.
