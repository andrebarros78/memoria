# MEMORIA-PERMANENTE — Baseline 0.15.2 Proof

- Result: **PASS**
- API: `0.15.2`
- Schema: `memory-0.15.2`
- Ontology: `KO-1.0.0`
- PostgreSQL: `18.6`
- pgvector: `0.8.6`
- Core tests: `61 passed in 0.93s`
- Adapter tests: `4 passed in 0.03s`
- Migrations: `20/20` checksums matched
- P07: `PROVEN / VALIDATED`
- Backup SHA-256: `05F766960D099E87786086C7DA0B5BB451AC12D27DFDC2C1C31F902E72D5C47D`
- Backup catalog entries: `399`
- Wheel SHA-256: `7d785bd07930d574d7f54bb140296ca630a163c9c2fd2bcd2705f1e2f22029e0`
- Audit DAG: `PASS`
- Secret path scan: `PASS`

Recovery note: the custom-format dump is valid and its restore catalog was verified. A new isolated database restore was not executed because the retained runtime role is intentionally non-CREATEDB and the historical administrative credential files are absent.
