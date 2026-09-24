# MEMORIA-PERMANENTE — Baseline 0.22.0

## Escopo

Baseline que consolida MEMORIA PLUS 14 — Memória operacional B2.

## Implementação comprovada

- Domínio `OM-1.0.0`: COMPETENCY, SKILL, SKILL_VERSION e CAPABILITY.
- Estados governados: PROVEN, STALE, FAILED e DEPRECATED.
- PROVEN exige REPLAY PASS + RECOVERY PASS frescos; falha/stale obriga nova prova.
- Supersessão de versão marca a versão PROVEN anterior como STALE.
- DEPRECATED é terminal; provas e status são append-only.
- Seis entidades operacionais com bitemporalidade, RLS/FORCE RLS e canonical mutation boundary.

## Gates

- P14: 45/45 PASS
- Core: 120 passed in 1.64s
- Adapter: 4 passed in 0.04s
- Audit: PASS (3882 eventos)
- Backup + pg_restore: PASS
- Wheel: PASS

## Governança

`V4_FULL_PROVEN = NÃO`. Próxima prioridade canônica: 15.
