# MEMORIA PLUS — Prioridades de Correção e Evolução

**Tag canônica:** `MEMORIA PLUS`
**Produto:** MEMORIA-PERMANENTE V4
**Estado:** OPEN / execução ordenada
**Regra:** itens P0 devem ser fechados antes da expansão funcional P1/P2 e antes de qualquer declaração `V4_FULL_PROVEN`.

## P0 — Integridade, confiança e fronteira canônica

### 01. Canonical Mutation Service único
**Problema:** ainda existem caminhos internos capazes de chamar `store.remember()` diretamente, contornando o Gateway.
**Bloco de correção:** criar uma única fronteira obrigatória para toda mutação persistente; proibir writes diretos fora dela; adicionar teste arquitetural que falha se surgirem novos caminhos diretos.
**Aceitação:** toda gravação/revisão/ingestão/experiência passa por policy + sanitização + proveniência + validação.

### 02. Sanitização de todos os payloads persistentes
**Problema:** criação/revisão já passam pelo sanitizer, mas outros JSON persistidos ainda podem carregar segredos.
**Bloco de correção:** sanitizar `validation.evidence`, `application.context`, `outcome.expected`, `outcome.actual`, `outcome.evidence`, ingestão, checkpoints, context packs e todo payload persistente.
**Aceitação:** nenhum payload chega ao storage sem `SecretSanitizer` e teste adversarial.

### 03. Outcome Learning vinculado à versão
**Problema:** outcome de uma aplicação ligada a V1 ainda pode alterar a confiança projetada no item já revisado para V2.
**Bloco de correção:** introduzir aprendizado e contadores por `version_id/content_sha256`; item atual vira somente projeção da versão corrente.
**Aceitação:** outcome atrasado de V1 nunca altera confiança de V2.

### 04. Learning Policy Engine
**Problema:** o chamador ainda pode informar `confidence_delta`.
**Bloco de correção:** transformar sucesso/falha/evidência em entrada; calcular ajuste de confiança no servidor por política versionada usando qualidade de evidência, repetibilidade, amostra, recência, independência e atribuição.
**Aceitação:** consumidor não escolhe diretamente o delta de confiança.

### 05. Eliminar autenticação especial `/v1/governor/*`
**Problema:** coexistem HMAC/capabilities universais e um contrato legado específico com `X-Governor-Key`.
**Bloco de correção:** migrar todos os consumidores para `MEMORIA-CLIENT-ADAPTER` universal + HMAC + capabilities; remover exceção pública específica.
**Aceitação:** um único modelo Zero Trust para todo consumidor.

### 06. Dependency Graph para derivados
**Problema:** revisão invalida validação/governor eligibility/embedding, mas não existe dependência genérica para demais artefatos derivados.
**Bloco de correção:** criar registro de dependências `artifact -> source version/hash` e estados `READY|STALE|INVALID`; propagar invalidação transacionalmente.
**Aceitação:** mudança de versão torna todos os derivados dependentes STALE/INVALID.

## P1 — Semântica, experiência e estrutura do conhecimento

### 07. Ontologia formal de conhecimento
**Problema:** `category` ainda é texto livre e não há regras semânticas globais.
**Bloco de correção:** formalizar `FACT, HYPOTHESIS, EVIDENCE, OBSERVATION, INFERENCE, CORRELATION, CAUSE, PROCEDURE, DECISION, INTERVENTION, OUTCOME, EXPERIMENT, LEARNING, CONSTRAINT, OBJECTIVE` e regras de relação/transição.
**Aceitação:** tipos e relações inválidas são rejeitados pelo domínio/schema.

### 08. Experience Graph completo
**Problema:** existe apenas um grafo mínimo `DECISION→MEMORY→APPLICATION→OUTCOME`.
**Bloco de correção:** modelar entidades first-class e relações `HYPOTHESIS→EVIDENCE→DECISION→INTERVENTION→RESULT→LEARNING/KNOWLEDGE`.
**Aceitação:** uma missão pode ser reconstituída causal e temporalmente pelo grafo.

### 09. Memória causal
**Problema:** `expected/actual` existe, mas sucesso é insuficiente para afirmar causa.
**Bloco de correção:** adicionar hipótese, intervenção, comparator/control, confounders, mecanismo, counterfactual, attribution confidence, sample size e repetição.
**Aceitação:** `CAUSE` só é promovido sob política causal explícita e evidência suficiente.

### 10. Memória de decisões e missões formal
**Problema:** missão/checkpoint é forte, mas decisão ainda é principalmente referência textual.
**Bloco de correção:** entidade `DECISION` com objetivo, contexto, alternativas, evidências usadas, razão, autoridade, ação, expected outcome, actual outcome e prova.
**Aceitação:** cada decisão crítica pode ser explicada e reexecutada a partir do registro soberano.

### 11. `GLOBAL_USER` como escopo canônico
**Problema:** escopo semântico e ACL estão misturados conceitualmente; `GLOBAL_USER` não existe no código atual.
**Bloco de correção:** separar `memory_scope = GLOBAL_USER|PROJECT|MISSION|SESSION` de `sharing_scope = PRIVATE_USER|PROJECT_SHARED|AGENT_PRIVATE|AGENT_TEAM|ORGANIZATION_SHARED|SYSTEM_SHARED`; manter “Memória Geral” apenas como label humano.
**Aceitação:** migrations/APIs/ACLs usam `GLOBAL_USER` como código canônico.

### 12. Bitemporalidade completa
**Problema:** `occurred_at/observed_at` existe apenas em parte; `created_at` ainda é usado como validade em alguns fluxos.
**Bloco de correção:** formalizar `occurred_at`, `observed_at`, `valid_from/valid_to`, `created_at` em todas as entidades temporais.
**Aceitação:** eventos tardios preservam tempo real do fato e tempo de conhecimento separadamente.

## P2 — Domínios avançados, lifecycle e conformidade

### 13. Memória econômica
**Problema:** não existem entidades formais para produto, SKU, campanha, anúncio, estoque, margem, capital e resultado econômico.
**Bloco de correção:** criar ontologia econômica e integrar com Experience Graph/bitemporalidade.
**Aceitação:** resultado econômico pode ser atribuído a decisões/intervenções/evidências com histórico temporal.

### 14. Memória operacional B2
**Problema:** há mecanismos operacionais, mas não memória formal de competências.
**Bloco de correção:** modelar `COMPETENCY, SKILL, SKILL_VERSION, CAPABILITY, PROVEN, STALE, FAILED, DEPRECATED`, replay proof e recovery proof.
**Aceitação:** sistema sabe quais competências estão comprovadas, em qual versão e com qual evidência.

### 15. InputGuard de segunda geração
**Problema:** detector atual melhorou, mas continua majoritariamente lexical/determinístico.
**Bloco de correção:** ampliar para multilíngue, obfuscação, fragmentação entre registros, múltiplos encodings, anexos/tool outputs e ataques distribuídos.
**Aceitação:** suíte adversarial cobre ataques equivalentes e variações sem depender de frases exatas.

### 16. P0-UI-B / exclusão governada
**Problema:** UI pode classificar/visualizar, mas purge destrutivo seguro depende de lifecycle.
**Bloco de correção:** formalizar `P0-UI-A` não destrutivo e liberar `P0-UI-B` somente após M12; `DESCARTÁVEL→DELETE_ELIGIBLE` continua sem purge direto.
**Aceitação:** UI nunca executa exclusão física fora do lifecycle governado.

### 17. Lifecycle Manager / Gate M12
**Problema:** falta ciclo completo de retenção, arquivamento, expiração, quarantine, tombstone e purge governado.
**Bloco de correção:** implementar lifecycle manager com políticas, holds, aprovação, recovery tests, audit e gate M12.
**Aceitação:** purge só ocorre sob política/autoridade/prova e é recuperável conforme contrato até o ponto de irreversibilidade.

### 18. Apagamento legal versus backups/manifests
**Problema:** não existe política completa para direito ao apagamento em dados presentes em backups/manifests/âncoras.
**Bloco de correção:** erasure ledger, crypto-shredding, tombstone mínimo, retenção de backup e fluxo `RESTORE → ERASURE REPLAY → SERVE TRAFFIC`; evitar hashes que preservem informação sensível por dictionary attack.
**Aceitação:** restore não ressuscita conteúdo legalmente apagado e manifestos não retenham dados recuperáveis.

## Ordem executiva canônica

`01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 → 10 → 11 → 12 → 13 → 14 → 15 → 16 → 17 → 18`

## Estado de fechamento

Enquanto os itens P0 (01–06) não estiverem comprovados:

- `M3 = REABERTO`
- `V4_FULL_PROVEN = NÃO`
- `V5_ADVANCE = BLOQUEADO`
- `MISSION_PROVEN = NÃO`
