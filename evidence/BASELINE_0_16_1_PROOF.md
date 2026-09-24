# MEMORIA-PERMANENTE — Baseline 0.16.1 Proof

Result: **PASS**

- API: `0.16.1` / `ok`
- Schema: `memory-0.16.1`
- Experience Graph: `EG-1.0.0`
- Ontology: `KO-1.0.0`
- Core pytest: `70 passed in 1.40s`
- Adapter pytest: `4 passed in 0.08s`
- Migrations: `22` exact byte matches
- P08: `PROVEN / VALIDATED`
- Audit: `PASS`
- Backup SHA-256: `5268B7B75B4C8D22E03BFF518F08DB017828DDAD644F318F45BB757D34551B18`
- pg_restore full render: `PASS`
- Wheel SHA-256: `8229be7f22130c9a9d63bb39408fc9cae49fa36ed63dcc8cd6af14c67867f2f6`
- Staged security scan: `PASS`

An isolated database restore was not repeated because the retained operational PostgreSQL role has `CREATEDB=false`; the post-P08 dump was nevertheless fully parsed/rendered by `pg_restore` with return code 0.

`V4_FULL_PROVEN` remains false. The next canonical MEMORIA PLUS priority is 09.
