# BASELINE OPERACIONAL CANÃ”NICA â€” V5.5

> **Snapshot de origem:** esta peÃ§a preserva a prova da baseline `0.29.3`. O runtime atual `0.30.0` a estende com F01/F02 sem invalidar estas provas; o estado cognitivo corrente Ã© registrado em `03_V5_5_TO_COGNITIVE_RECONCILIATION.md`.


**Estado:** `PROVEN_CURRENT`  
**Produto:** `MEMORIA-PERMANENTE`  
**VersÃ£o:** `0.29.3`  
**Runtime:** `V5.5-PRIMARY`  
**Release:** `MEMORIA_PERMANENTE_CANONICAL_1.0`

## Estado comprovado

A baseline V5.5 possui 53 mÃ³dulos Python ativos no core, 76 arquivos de testes, 54 migrations, PostgreSQL 18.6, pgvector 0.8.6, APIs canÃ´nicas 8787/8790, workers de ingestion/embedding, 4 agentes, 6 skills e 15 camadas de seguranÃ§a declaradas pelo runtime.

Capacidades comprovadas incluem retrieval lexical e semÃ¢ntico, contexto, checkpoint/resume, bitemporalidade, ontologia, Experience Graph, causalidade governada, decisÃ£o, memÃ³ria operacional, learning policy, lifecycle/legal erasure, backup/restore, integrity anchor, MCP, consumer adapter, conversational adapter e AI Integration governada.

## Fronteira de IA vigente

O core `0.29.3` nÃ£o contÃ©m inferÃªncia concreta de LLM. `OFFICIAL_ADAPTERS` Ã© restrito a `REST_OPENAPI`, `MCP`, `MEMORY_CLIENT`, `AI_INTEGRATION` e `CONVERSATIONAL`.

```text
IA externa sugere
â†’ polÃ­tica valida
â†’ memÃ³ria governa
```

## Provas atuais

- full regression: `340 passed`, `2 POSIX-only skipped`, `0 failed`;
- seguranÃ§a focada: `101/101 passed`;
- Ruff: PASS;
- compileall: PASS;
- isolated pip check: PASS;
- V5.5 live runtime: PASS;
- `restart_recovery_verified=true`;
- `conformance_compatible=true`;
- Agent+Skill E2E: PASS;
- `restart_verified=true`.

Wheel comprovado:

```text
memoria_permanente-0.29.3-py3-none-any.whl
SHA-256: bb7e7a5ab0d0116706cf4f293f31c42eb53592cb239c3c97a3b14227272f29cc
```

Commit de fronteira do core: `7088f09a92a76b34921872ba29cacc17f7e50818`.

## RelaÃ§Ã£o com a evoluÃ§Ã£o cognitiva

| Capacidade | Baseline V5.5 | Estado documental |
|---|---|---|
| Captura/versionamento | implementado | PROVEN_CURRENT |
| Retrieval lexical/semÃ¢ntico | implementado | PROVEN_CURRENT |
| Contexto/checkpoints | implementado | PROVEN_CURRENT |
| Bitemporalidade | implementado | PROVEN_CURRENT |
| Ontologia | implementado | PROVEN_CURRENT |
| Experience Graph | implementado | PROVEN_CURRENT |
| Causalidade | implementado | PROVEN_CURRENT |
| DecisÃ£o | implementado | PROVEN_CURRENT |
| Procedural/operacional | implementado | PROVEN_CURRENT |
| Aprendizado por resultado | implementado | PROVEN_CURRENT |
| AtivaÃ§Ã£o cognitiva explÃ­cita | nÃ£o implementada | PLANNED |
| Priming explÃ­cito | nÃ£o implementado | PLANNED |
| SaliÃªncia afetiva funcional | nÃ£o implementada | PLANNED |
| Spreading activation | nÃ£o implementado como motor | PLANNED |
| ConsolidaÃ§Ã£o cognitiva offline | nÃ£o implementada como motor autÃ´nomo | PLANNED |
| ReconsolidaÃ§Ã£o profunda pÃ³s-recall | nÃ£o implementada como motor | PLANNED |
| GeneralizaÃ§Ã£o conceitual contÃ­nua | fundaÃ§Ãµes parciais | FOUNDATION_PRESENT |
| MemÃ³ria prospectiva sofisticada | nÃ£o implementada | PLANNED |
| Embodied/sensÃ³rio-motora | integraÃ§Ãµes externas/fundaÃ§Ãµes | FOUNDATION_PRESENT / PLANNED |
| ConsciÃªncia/emoÃ§Ã£o biolÃ³gica | nÃ£o Ã© objetivo | OUT_OF_SCOPE |

## LimitaÃ§Ãµes da baseline

Linux runtime real e `DISTRIBUTED_HA` ainda nÃ£o foram comprovados. PostgreSQL ainda usa path fÃ­sico histÃ³rico/legacy-named. HÃ¡ um warning de depreciaÃ§Ã£o Starlette/anyio no harness de teste. Nenhum desses pontos torna provider de LLM requisito do core.
