# MEMORIA-PERMANENTE baseline 0.20.0

Baseline da prioridade MEMORIA PLUS 12 — Bitemporalidade completa.

## Estado

- API `0.20.0`
- Schema `memory-0.20.0`
- Bitemporalidade `BT-1.0.0`
- PostgreSQL `18.6` / pgvector `0.8.6`
- 27 migrations imutáveis
- P12 `PROVEN / VALIDATED` (versão 3)
- Core 95/95 PASS
- Adapter 3/3 PASS
- Audit DAG PASS
- Backup terminal `memory-20260902-143548.dump` SHA-256 `6197c8079d676af4d09396a312b2a320a75707c9494fae0d4dfffac7116a6c12`
- Wheel `memoria_permanente-0.20.0-py3-none-any.whl` SHA-256 `eb90864ed0aa27901acba4dab00ab1ea9827821ac1a936a24f7b40e672ff775c`

## Contrato P12

As entidades temporais de domínio separam `occurred_at`, `observed_at`, `valid_from`, `valid_to` e `created_at`. `created_at` representa persistência e não é usado como validade. Consultas bitemporais aceitam `valid_at` e `known_at`, e eventos tardios preservam tempo do fato e tempo de conhecimento.

`V4_FULL_PROVEN = NÃO`; prioridades posteriores permanecem pendentes.

- Git security scan: PASS (19 candidate files; no forbidden paths or secret hits).
