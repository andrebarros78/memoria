# MEMÓRIA PERMANENTE V4 — CHECKPOINT P1–P8 + PAINEL

**Data:** 24/08/2026 — horário de Brasília
**Projeto soberano:** `C:\New Projet\MEMORIA-PERMANENTE`
**Estado:** CHECKPOINT COMPROVADO

## Prioridades estruturais

| Prioridade | Estado | Prova |
|---|---|---|
| P1 — módulo independente | PASS | `evidence/P1_STRUCTURE_PROOF.json` |
| P2 — banco soberano separado | PASS | `evidence/P2_DB_SERVICE_ISOLATION_PROOF.json` |
| P3 — componentes comprovados reaproveitados | PASS | `evidence/P3_REUSED_COMPONENTS_PROOF.json` |
| P4 — Memory Gateway REST/OpenAPI/MCP | PASS | `evidence/P4_MEMORY_GATEWAY_PROOF.json` |
| P5 — Memory Client Adapter | PASS | `evidence/P5_MEMORY_CLIENT_ADAPTER_PROOF.json` |
| P6 — independência bidirecional | PASS | `evidence/P6_*` |
| P7 — migração com integridade | PASS | `evidence/P7_DATA_MIGRATION_PROOF.json` |
| P8 — Gate M10 | PASS | `evidence/P8_GATE_M10_PROOF.json` |

## Gate M10

```text
GATE_M10 = PASS
MEMORY_MODULE_INDEPENDENCE_PROVEN = TRUE
```

A Memória Permanente opera em raiz, banco, serviço, API e ciclo de vida próprios. O Governor usa `MemoryClientAdapter` por contrato HTTP público e não possui acesso direto ao banco soberano da memória.

## Painel Operacional

```text
PAINEL_OPERATIONAL_PROVEN = PASS
V5_PANEL_PRIORITY_CRITERION_SATISFIED = TRUE
```

Prova: `evidence/PAINEL_OPERATIONAL_GATE_PROOF.json`.

O painel comprova em runtime real:

- saúde e resumo;
- busca/listagem;
- classificação PERMANENTE/ATIVA/ARQUIVADA/DESCARTÁVEL/PROTEGIDA;
- `DESCARTÁVEL -> DELETE_ELIGIBLE`, sem exclusão direta;
- geração de relatório `.md`;
- OpenAPI;
- restart independente da API/painel;
- PostgreSQL soberano em serviço próprio;
- purge direto bloqueado por HTTP 405.

## Migração

```text
memory_items       126 / 126
retrieval_traces   384 / 384
checkpoints        249 / 249
legacy_audit       1770 / 1770
DATA_LOSS          0
UNEXPLAINED_DUPLICATION 0
ROLLBACK_DRILL      PASS
```

## Não regressão do Governor

```text
52 / 52 PASS
TrustGuard = PASS
release_generation = 36
MemoryClientAdapter protected = TRUE
```

## Pendências V4 posteriores ao M10

A aprovação de M10 e do Painel não significa aprovação integral da V4.

Próximas frentes obrigatórias:

1. retrieval semântico / pgvector com prova de qualidade e regressão;
2. Session Rotation / Gate M9;
3. AI Session & RAM Governor / Gate M11;
4. homologação do runtime PostgreSQL conforme alvo documental da V4 (ambiente atual: PostgreSQL 17.10; alvo documental: 18.6);
5. demais gates V4 ainda não comprovados por evidência atual.

```text
V5_ADVANCE = BLOCKED_UNTIL_V4_COMPLETE
```
