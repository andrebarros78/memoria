# BASELINE 0.14.2 — PROVA TÉCNICA

**Resultado:** PASS

- API: `0.14.2` / healthy
- Schema: `memory-0.14.2`
- PostgreSQL: `18.6`
- pgvector: `0.8.6`
- Testes MEMORIA-PERMANENTE: `55 passed in 1.00s`
- Testes MEMORIA-CLIENT-ADAPTER: `4 passed in 0.03s`
- Migrations: `0001 â†’ 0017`, checksums arquivoâ†”DB = `True`
- MEMORIA PLUS 05/06: `PASS` / `PROVEN + VALIDATED`
- Governor legado ativo: `0`
- Audit events: `3412`, invalid_hash=`0`, missing_parent=`0`
- Backup válido: `True` / SHA-256 `2B5CF577E0A2AED52909844C44E9423E6CC1C4CEE5AAD4B43914E85BCE61CA07`
- Wheel limpo: `True` / SHA-256 `868ef8b54dacb7481ac187da875b22e74e8baf4b8f7a4d38b6f0323497e8f4f2`

## Resultado P05

Autenticação específica do Governor foi removida da API pública. Consumidores usam o Adapter Universal 1.1.0 com autenticação HMAC/capabilities. A rota legada assinada retorna 404 e não existem bindings Governor ativos.

## Resultado P06

Dependências derivadas ficam vinculadas a `item_id + version_id + content_sha256`. Na revisão V1â†’V2, `CHECKPOINT`, `CONTEXT_PACK`, `EMBEDDING`, `RETRIEVAL_TRACE` e `SESSION_CHECKPOINT` vinculados à V1 foram marcados `STALE`; derivado novo de V2 permaneceu `READY`.

## Correções encontradas durante a prova

1. Migration `0016` não via bindings de tenants históricos sob FORCE RLS. O runner passou a executar migrations com `app.current_tenant=__SYSTEM__`, e `0017` reconciliou todos os bindings legados.
2. Git normalizava bytes de migrations aplicadas, provocando `MigrationDriftError`. `.gitattributes` passou a preservar bytes de migrations; checksums atuais coincidem 100% com `schema_migrations`.
3. Build incremental carregou módulos Governor removidos a partir de `build\lib`. O build foi tornado clean-build e o wheel final foi inspecionado: zero entradas Governor legadas.
