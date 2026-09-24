# MEMORIA-PERMANENTE — Baseline 0.16.1

Data: 2026-09-02

Esta baseline fecha a **MEMORIA PLUS prioridade 08 — Experience Graph completo**.

## Estado comprovado

- API `0.16.1`
- schema `memory-0.16.1`
- Experience Graph `EG-1.0.0`
- ontologia `KO-1.0.0`
- PostgreSQL `18.6`
- pgvector `0.8.6`
- migrations `0001–0022` com checksum byte a byte preservado
- Core pytest `70/70 PASS`
- MEMORIA-CLIENT-ADAPTER `4/4 PASS`
- P08 `PROVEN / VALIDATED`
- audit DAG íntegro, sem hash inválido ou pai ausente

## P08

O sistema passa a manter entidades first-class de experiência:

`HYPOTHESIS → EVIDENCE → DECISION → INTERVENTION → RESULT → LEARNING → KNOWLEDGE`

Arestas causais são tipadas, temporais, protegidas contra ciclos e escopo cruzado, com RLS/FORCE RLS e registros append-only. Nós podem ser vinculados a uma versão exata de memória, preservando a semântica histórica mesmo após revisão ou transição ontológica da memória original.

A reconstrução por missão produz timeline e ordem causal determinísticas. A prova P08 validou 29 controles, incluindo rejeições no domínio/API e no PostgreSQL.

## Recuperação e release

Backup pós-P08:

- SHA-256 `5268B7B75B4C8D22E03BFF518F08DB017828DDAD644F318F45BB757D34551B18`
- catálogo `pg_restore`: 432 entradas
- renderização integral pelo `pg_restore`: PASS (`RC=0`)

A role operacional retida possui `CREATEDB=false`; por isso um novo banco isolado não foi criado nesta baseline. O dump foi integralmente lido/renderizado pelo `pg_restore`, sem alteração do banco ativo.

Wheel `0.16.1`:

- SHA-256 `8229be7f22130c9a9d63bb39408fc9cae49fa36ed63dcc8cd6af14c67867f2f6`
- conteúdo proibido: nenhum

## Governança

`V4_FULL_PROVEN` permanece **não declarado**. A próxima prioridade canônica da MEMORIA PLUS é **09**.

Provas principais:

- `evidence/MEMORIA_PLUS_P08_PROOF.json`
- `evidence/MEMORIA_PLUS_P08_REGISTRY_UPDATE.json`
- `evidence/BASELINE_0_16_1_PROOF.json`
