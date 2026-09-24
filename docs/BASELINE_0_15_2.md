# MEMORIA-PERMANENTE — Baseline 0.15.2

Data: 2026-09-02

Esta baseline fecha a prioridade **MEMORIA PLUS 07 — Ontologia formal de conhecimento**.

## Estado

- API `0.15.2`
- schema `memory-0.15.2`
- ontologia `KO-1.0.0`
- PostgreSQL `18.6`
- pgvector `0.8.6`
- migrations `0001–0020` com checksum byte a byte preservado
- 15 tipos canônicos de conhecimento
- 96 regras formais de relação
- 7 regras formais de transição
- P07 `PROVEN / VALIDATED`
- testes core `61/61 PASS`
- testes MEMORIA-CLIENT-ADAPTER `4/4 PASS`
- auditoria DAG `PASS`
- backup pós-P07 válido e catálogo de restore verificado
- wheel `0.15.2` verificado, sem módulos Governor legados nem material de chave
- `V4_FULL_PROVEN`: não declarado
- `MISSION_PROVEN`: não declarado para o projeto total

A próxima prioridade canônica da `MEMORIA PLUS` é **08**.

## Evidências

- `evidence/MEMORIA_PLUS_P07_PROOF.json`
- `evidence/MEMORIA_PLUS_P07_PROOF.md`
- `evidence/MEMORIA_PLUS_P07_REGISTRY_UPDATE.json`
- `evidence/BASELINE_0_15_2_PROOF.json`
- `evidence/BASELINE_0_15_2_PROOF.md`

## Nota de recuperação

O dump custom-format pós-P07 foi validado e seu catálogo foi lido integralmente por `pg_restore --list`. Um restore para novo banco isolado não foi executado nesta baseline porque o runtime retido possui somente a role `memory_app` com `CREATEDB=false`, e as credenciais administrativas históricas utilizadas no gate M4 não estão mais presentes. Esta limitação é registrada explicitamente; não é alegado um restore isolado que não tenha sido executado.
