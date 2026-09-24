# MEMORIA-PERMANENTE — Baseline 0.21.0

## Escopo

Baseline que consolida MEMORIA PLUS 13 — Memória econômica.

## Implementação comprovada

- Ontologia `EM-1.0.0`: PRODUCT, SKU, CAMPAIGN, AD, INVENTORY, MARGIN, CAPITAL e resultados econômicos.
- Atribuições server-side para decisão soberana, intervenção, evidência, entidade e estado econômico.
- Snapshots SHA-256 imutáveis preservam explicação histórica após evolução das fontes.
- Integração com Experience Graph e bitemporalidade BT-1.0.0.
- RLS/FORCE RLS, append-only e canonical mutation boundary nas tabelas econômicas.

## Gates

- P13: 40/40 PASS
- Core: 108 passed in 2.74s
- Adapter: 3 passed in 0.04s
- Audit: PASS (3844 eventos)
- Backup + pg_restore: PASS
- Wheel: PASS

## Governança

`V4_FULL_PROVEN = NÃO`. Próxima prioridade canônica: 14.
