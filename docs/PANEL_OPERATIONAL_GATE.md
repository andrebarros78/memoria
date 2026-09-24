# PAINEL OPERACIONAL — GATE PRIORITÁRIO V4 -> V5

**Data:** 24/08/2026
**Prioridade:** CRITICAL
**Estado:** EM CONSTRUÇÃO
**Objetivo:** `PAINEL_OPERATIONAL_PROVEN`

## Regra de avanço

A evolução operacional da V4 para V5 não é liberada antes da construção, integração, teste e comprovação deste painel.

## Requisitos mínimos

- visual profissional, moderno, limpo e responsivo;
- indicadores de saúde, volume, permanência, ativação, aprendizado, reutilização e taxa de sucesso;
- busca e filtros;
- seleção individual e em lote;
- classes humanas `PERMANENTE`, `ATIVA`, `ARQUIVADA`, `DESCARTÁVEL`, `PROTEGIDA`;
- geração de relatório operacional `.md`;
- auditoria das alterações;
- ausência de exclusão direta;
- `DESCARTÁVEL -> DELETE_ELIGIBLE`;
- purge somente em fluxo futuro reference-safe + hold-safe + quarantine + audit.

## Evidência necessária para PASS

1. painel inicia em runtime isolado;
2. API `/health` responde;
3. resumo operacional usa dados reais do banco soberano;
4. lista e filtros retornam dados reais;
5. classificação individual funciona;
6. classificação em lote funciona;
7. `DESCARTÁVEL` nunca remove registro;
8. `PERMANENTE/PROTEGIDA` criam proteção compatível;
9. relatório `.md` é gerado com dados reais;
10. reinício preserva classificações;
11. testes automatizados passam;
12. evidência reproduzível é gravada em `evidence/`.

Somente então:

```text
PAINEL_OPERATIONAL_PROVEN
V5_ADVANCE_GATE = PASS
```
