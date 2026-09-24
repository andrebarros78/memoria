# V4 + V5.2 Integration Promotion Proof - 2026-09-04

Status: V5.2_PRIMARY_PROMOTED_WITH_V4_ROLLBACK_PROVEN

## Resultado

A V5.2 foi promovida para a porta principal 127.0.0.1:8787 usando o banco memoria_permanente_v52_primary.
A V4 foi preservada como rollback por banco original e worktree imutavel em C:\New Projet\MEMORIA-PERMANENTE-V4-ROLLBACK.

## Evidencias principais

- Health principal: untime_profile=V5.2-PRIMARY, elease_channel=primary-promoted.
- API sem assinatura em painel humano: 401.
- API assinada: 200.
- Painel humano: V5.2_HUMAN_OPERATIONAL_VIEW, 8 memorias.
- Explainability: RETRIEVAL_EXPLAINABILITY_V1, selected_count=1, modos LEXICAL + SEMANTIC.
- MCP: memory_human_view PASS, direct_database_access=false.
- V4 rollback: worktree em c77686471dbec0b53002b8d2653cf7dcb90b658f, tag mission-proven-0.26.1-20260904, start test PASS.
- RC1 secundaria 8792: parada para evitar ambiguidade operacional.
- Recovery: dump PASS, restore PASS, pg_amcheck PASS, paridade 76/76 tabelas.
- Testes: 186/186 PASS.
- Defender: 0 ameacas associadas ao projeto.

## Estado final

- Principal: V5.2 em 127.0.0.1:8787.
- Observabilidade legacy: Phoenix em 127.0.0.1:6006.
- Observabilidade V5.2: /metrics assinado + etrieval_traces + /v1/observability/v52.
- Rollback: V4 preservada por script e worktree separado.

MISSION_PROVEN
