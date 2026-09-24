# MEMORIA-PERMANENTE 0.28.1 — Prova Terminal

Data: 06/09/2026 — horário de Brasília.

## Resultado técnico

**PASS** para o candidato final `0.28.1`.

Commit técnico comprovado: `1c2a56cd44a530cfb3029cca9f01d9c2c0e4533d`
Árvore Git comprovada: `87e515a8bb490b728569358189a2797bc3a514d7`

A decisão `MISSION_PROVEN` somente é válida quando a tag `baseline-0.28.1` apontar para o commit documental que contém esta prova, a working tree estiver limpa e o runtime canônico isolado continuar saudável.

## Runtime comprovado

- Perfil: `V5.3-PRIMARY`.
- Release channel: `v5.3-primary-promoted`.
- API/package: `0.28.1`.
- Execução de produção: `runtime/api-clean` em modo Python `-I`.
- `PYTHONPATH` herdado removido no launcher.
- Pacote carregado de `runtime/api-clean/Lib/site-packages` e não de `src`.
- PostgreSQL `18.6`.
- pgvector `0.8.6`.
- Role de runtime: `memory_app`, não privilegiada.
- Schema: 51 migrações, head `0051_reserved_system_and_restore_gate_hardening`.

## Release

Wheel: `memoria_permanente-0.28.1-py3-none-any.whl`
SHA-256: `75282d46a34f44c95323697f450d0ea56e44492650494e5e4f7d8920fe371ab7`

Verificação do wheel: recursos presentes, 51 migrações presentes, nenhum artefato proibido e `clean=true`.

## Regressão terminal

- Compile: PASS.
- Ruff: PASS.
- mypy: PASS — 48 arquivos de source sem issues.
- Bandit: PASS.
- Pytest: **318 passed, 2 skipped**.
- Warning restante: depreciação Starlette/AnyIO de terceiro; não reprovou funcionalidade ou segurança.
- `pip check` venv de desenvolvimento: PASS.
- `pip-audit`: PASS; o pacote local não publicado é apenas reportado como não auditável no PyPI.
- `pip check` de `api-clean`: PASS.
- `pip check` do auditor isolado: PASS.
- Parser PowerShell de launch/recovery/auditor: PASS.
- `git diff --check`: PASS.
- Varredura de padrões de segredos rastreados: PASS.

## Provas vivas de segurança

- Autenticação HMAC: **12/12 PASS**.
- Tentativas cross-tenant contra `SECURITY DEFINER`: bloqueadas com SQLSTATE `42501`.
- Bypass de tenant reservado `__SYSTEM__`: bloqueado.
- Runtime impedido de abrir o restore gate: SQLSTATE `42501`.
- Fronteira de artefatos derivados: PASS.
- Auditor de retrieval com OPA/Phoenix: PASS.
  - pass rate: `1.0`;
  - scope leaks: `0`;
  - API failures: `0`;
  - conflicts: `0`;
  - Phoenix health: `true`.

## Agentes e Skills

- Agent/Skill E2E: PASS.
- Agentes carregados: `4`.
- Skills callable: `6`.
- Memória E2E persistiu após restart.
- Checkpoint persistiu após restart.
- Retrieval pós-restart: PASS.
- `restart_verified=true`.
- Agente de evolução terminal: `PASS`.

## Backup e recuperação

Backup: `v52-20260906T144714Z-3d89d37a`.

- Criptografia: AES-256-GCM.
- Ciphertext SHA-256: `88c1c3a971f1f34f8de7091105b7757b14f918e7cf3d5f68bf7cce80bb19b715`.
- Manifest SHA-256: `8b64a313c4a1aed61064489a6859f375630df80b249bed59bcd58807e86fc4ca`.
- Plaintext residual: não retido.
- Restore isolado: PASS.
- `pg_amcheck`: PASS.
- Audit chain: PASS, 349 eventos verificados.
- Erasure replay: PASS.
- Preflight pós-restore: PASS como `memory_app` não privilegiado.

## Defesa em profundidade comprovada

1. HMAC-SHA256, nonces anti-replay e capabilities escopadas.
2. Bearer de navegador somente leitura e mutações negadas.
3. PostgreSQL RLS por tenant.
4. Bloqueio do contexto reservado `__SYSTEM__` para runtime.
5. Wrappers `SECURITY DEFINER` com boundary de tenant e `search_path` seguro.
6. Role `memory_app` de mínimo privilégio.
7. Fronteira de artefatos derivados sem escrita direta.
8. Validação de loopback/origem e bloqueio de redirects em clientes assinados.
9. Limites de corpo/resposta HTTP e política de rede fail-closed.
10. Credenciais protegidas por DPAPI e sanitização ampliada de segredos.
11. Runtime imutável por wheel, `python -I` e ausência de `PYTHONPATH=src`.
12. Backup AES-256-GCM autenticado e sem retenção de plaintext.
13. Audit chain, Phoenix/OpenTelemetry e OPA para qualidade de retrieval.
14. Ruff, mypy, Bandit, dependency checks, CVE audit, regressão, restart e recovery.

## Limite da afirmação de segurança

Não há promessa de invulnerabilidade absoluta. A prova demonstra redução objetiva da superfície de ataque com defesa em profundidade, Zero Trust, mínimo privilégio, isolamento, recuperação e testes reproduzíveis.

## Condição final

`MISSION_PROVEN` = válido somente se:

1. `baseline-0.28.1` apontar ao commit documental desta prova;
2. `git status --porcelain` estiver vazio;
3. `/health` continuar `ok` em `V5.3-PRIMARY`;
4. o listener 8787 continuar executando `runtime/api-clean/Scripts/python.exe -I -m uvicorn memory_permanent.api:app`.
