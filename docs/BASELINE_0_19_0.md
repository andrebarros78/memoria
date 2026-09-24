# MEMORIA-PERMANENTE — Baseline 0.19.0

## P11 — GLOBAL_USER como escopo canônico

- `memory_scope`: `GLOBAL_USER|PROJECT|MISSION|SESSION`.
- `sharing_scope`: `PRIVATE_USER|PROJECT_SHARED|AGENT_PRIVATE|AGENT_TEAM|ORGANIZATION_SHARED|SYSTEM_SHARED`.
- `GLOBAL_USER` é o código canônico; `Memória Geral` é somente label humano.
- O RLS continua usando `sharing_scope`; `memory_scope` não concede permissão.
- Context retrieval inclui `GLOBAL_USER` e apenas escopos contextuais com referência correspondente.

## Gates

- P11 proof: 40/40 PASS — `4cfbf40ba8c3ab2451a34ed34e5e0aeb64b77a68f2a8afc64af6ef9f0e4ac219`
- Core: 90 passed in 1.17s
- Adapter: 4 passed in 0.04s
- Audit: PASS — 3702 eventos
- Migrations: 0001–0026 exatas
- Backup: `f043f2b63e6e2422bd54eb56b40dfccfc97ec37fe35f8863d80adfdf74a83413`
- Wheel: `968f521308cc34e3cf2184f73bca047d41aeb6781995ba82b521e37e3168442b`

`V4_FULL_PROVEN = NÃO` após P11; prioridades posteriores permanecem pendentes.
