# Auditoria terminal de segurança e código — MEMORIA-PERMANENTE V5.3

Data operacional: 05/09/2026, horário de Brasília.

Baseline de entrada: `9406d1d2692f46de2ace808892f2f9d970f34556`
Branch: `v5.3-primary-20260904`

## Resultado

**PASS_WITH_REPOSITORY_MAINTENANCE_DEBT**

A superfície operacional V5.3 foi auditada, falhas críticas foram reproduzidas antes da correção, corrigidas e retestadas em banco vivo. O runtime, backup/restore e release foram novamente comprovados. Não se declara invulnerabilidade absoluta.

## Falhas críticas comprovadas e corrigidas

### AUD-CRIT-001 — bypass de tenant por contexto reservado `__SYSTEM__`

Antes da correção, o papel `memory_app` podia definir `app.current_tenant='__SYSTEM__'` e a função RLS aceitava esse valor sem validar o papel do banco. Prova pré-correção: tenant inexistente enxergou 0 itens; `__SYSTEM__` enxergou 19 itens.

Correção: migration `0051_reserved_system_and_restore_gate_hardening`.

Prova pós-correção: `reserved_system_visible_items=0` e `reserved_system_agent_bypass=false`.

### AUD-CRIT-002 — runtime podia abrir gate de recuperação

Antes da correção, `memory_app` conseguia executar `memory_set_runtime_gate()` e alterar `restore_erasure_replay_status` por uma fronteira `SECURITY DEFINER` excessiva.

Correção: `0051` restringe contexto reservado e a mutação de gates. O fluxo de restauração agora mantém o gate em `PENDING` e somente o plano administrativo o move para `PASS` após replay de erasure aprovado.

Prova pós-correção: runtime negado com SQLSTATE `42501`; owner da função = `memory_admin`.

## Outras falhas corrigidas

- `0050_security_definer_tenant_boundary`: wrappers de tenant explícitos para funções `SECURITY DEFINER`; quatro tentativas cross-tenant bloqueadas com SQLSTATE `42501`.
- `RecoveryIntegrityAgent`: bloqueio de caminhos absolutos e `../` fora da raiz do manifesto; manifesto inválido passa a falhar fechado.
- API: `/health` minimizado; `/v1/health/details` protegido por `memory:admin`; OpenAPI/docs/redoc públicos desabilitados.
- Autenticação: clientes da API não podem solicitar tenant ou agente `__SYSTEM__`.
- Secret Sanitizer: ampliação para tokens OpenAI/GitHub/Slack/Google/Stripe/JWT/AWS, bearer/proxy bearer, database URLs, cookies, private keys e campos sensíveis por nome/sufixo.
- UI: sessões bearer continuam somente leitura; controles de mutação/classificação foram removidos do navegador.

## Vazamento de segredos

Foram comparados 3 valores secretos atuais contra arquivos rastreados, blobs do histórico Git e logs de runtime, sem imprimir o material secreto.

- arquivos rastreados: 0 ocorrências;
- histórico Git: 0 ocorrências;
- logs de runtime: 0 ocorrências;
- vazamento plaintext detectado: **não**.

ACL dos diretórios operacionais de segredos: somente `SYSTEM` e usuário operacional do Windows.

## Banco e isolamento

- PostgreSQL: `18.6`;
- pgvector: `0.8.6`;
- runtime role: `memory_app`;
- runtime role privilegiado: `false`;
- migrations: `51`;
- migration head: `0051_reserved_system_and_restore_gate_hardening`.

## Provas vivas de segurança

- Security Definer Tenant Boundary: **PASS**;
- Reserved System + Restore Gate: **PASS**;
- HMAC/auth/anti-replay/capabilities: **12/12 PASS**.

Evidências correlatas:

- `evidence/SECURITY_DEFINER_TENANT_BOUNDARY_PROOF_20260905.json`
- `evidence/RESERVED_SYSTEM_RESTORE_GATE_LIVE_PROOF_20260905.json`
- `evidence/SECURITY_AUTH_HARDENING_LIVE_PROOF.json`

## Regressão terminal

- compileall: PASS;
- Ruff `src + tests`: PASS;
- mypy: PASS, 48 arquivos de fonte;
- Bandit `src`: PASS;
- pytest: **300 passed, 2 skipped**, 1 warning de depreciação Starlette/AnyIO de terceiro;
- `pip check`: PASS;
- `pip-audit --local`: PASS;
- `git diff --check`: PASS.

## Backup e recuperação

Backup criptografado:

- ID: `v52-20260906T004940Z-e8584873`;
- cifra: AES-256-GCM;
- SHA-256 ciphertext: `9f149845ec6914052ba8395c51282d8805195b05d9bc9be96f5df7ee1198011e`;
- manifesto autenticado: sim;
- plaintext retido: não.

Restore isolado:

- `pg_amcheck`: PASS;
- migrations após restore: 51;
- runtime preflight: READY;
- audit chain: válida, 294 eventos;
- erasure replay: PASS;
- fluxo: RESTORE → MIGRATE → ERASURE_REPLAY → VERIFY;
- dump temporário retido: não.

## Release auditado

Wheel: `memoria_permanente-0.28.0-py3-none-any.whl`

SHA-256: `efea18d77e5110649a339b79376fcd6200f78011f3460d595215954af484354d`

- 51/51 migrations presentes;
- zero entrada proibida;
- Product DNA presente;
- assets estáticos presentes;
- import direto do wheel, sem `PYTHONPATH=src`: PASS;
- hardening de path do RecoveryIntegrityAgent presente no wheel.

## Restart operacional

O processo canônico foi encerrado de forma controlada e iniciado por `.agents/recovery/start-api.ps1`.

Resultado:

- PostgreSQL V5.3 primary READY;
- runtime role `memory_app` não privilegiado;
- migration head `0051`;
- `/health` = `ok`;
- runtime profile `V5.3-PRIMARY`;
- release channel `v5.3-primary-promoted`;
- `API_RECOVERY_V53_READY`.

## Dívida de manutenção não pertencente ao runtime/release

Foram identificados 30 scripts históricos/de prova que ainda referenciam caminhos locais de credencial e o lint global desses scripts produz 215 achados. Esses scripts:

- não são chamados pela cadeia ativa `.agents/recovery` / `deploy/v5.3`;
- não entram no wheel do produto;
- não apresentaram vazamento dos segredos atuais no Git ou logs;
- devem ser refatorados para `PGPASSFILE` ou aposentados antes de qualquer reutilização operacional.

A cadeia ativa de deploy/recovery usa credenciais por arquivo protegido e não contém senha inline em DSN operacional.

## Conclusão técnica

As vulnerabilidades comprovadas na superfície operacional foram corrigidas e retestadas. A arquitetura atual mantém defesa em profundidade: HMAC/anti-replay, autorização por capability, RLS/FORCE RLS, papéis least-privilege, wrappers `SECURITY DEFINER` restritos, sanitização/cofre, isolamento de agentes/skills, API loopback, health fail-closed, audit chain, lifecycle/erasure governado, backup AES-256-GCM, restore com replay e `pg_amcheck`, scans estáticos/dependências, release hygiene e recuperação canônica.

O resultado reduz a superfície de ataque ao nível atualmente comprovado; não constitui promessa de invulnerabilidade absoluta.
