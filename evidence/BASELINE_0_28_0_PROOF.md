# MEMORIA-PERMANENTE — Baseline 0.28.0

Status: **PASS_BASELINE_VALIDATED**

- Release executável: `0.28.0`
- Marco funcional: `V5.3`
- Runtime: `V5.3-PRIMARY`
- Full pytest: `260 passed, 2 skipped`
- V5.3 focado: `15 passed`
- Migrations: `46/46` com SHA arquivo â†” banco idêntico
- RLS + FORCE RLS: ativo nas tabelas do AI Integration Adapter
- Runtime `memory_app`: `NOSUPERUSER` e `NOBYPASSRLS`
- Integridade privilegiada herdada da prova V5.3: `pg_amcheck primary=0`, restore=0, `78/78` tabelas, contagens iguais
- Health live: `0.28.0 / V5.3-PRIMARY`

A baseline preserva o princípio: IA externa sugere; a Memória Permanente governa, sanitiza, audita e promove somente pelo caminho canônico.
