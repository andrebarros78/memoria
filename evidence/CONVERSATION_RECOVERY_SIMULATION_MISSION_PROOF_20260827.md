# MEMORIA V4 — Prova de Simulação Isolada

- Gerado: 2026-08-27T15:14:31.673739-03:00
- Estado: **MISSION_PROVEN**
- PostgreSQL isolado: 18.6 / pgvector 0.8.6 / porta 55490
- API isolada: 127.0.0.1:8792
- Produção preservada: **SIM**
- Ciclos: 20
- Recuperação pós-restart: 20/20
- Memórias persistidas: 60
- Checkpoints: 20
- Context Packs: 20
- Audit chain: PASS (140 eventos)
- Embedding worker: 10/10, 0 falhas
- Pytest: 31/31 PASS
- Lookup médio: 306.983 ms
- Failed checks: []

## Regra comprovada

`conversation_id -> external_session_binding -> sovereign_session -> checkpoint -> Context Pack -> continuation payload`

Invisible Browser e Learning não participam deste caminho de recuperação.
