# RECONCILIAÇÃO CANÔNICA — V5.5 → MEMÓRIA UNIVERSAL COGNITIVA

## 1. Decisão arquitetural

A Memória Universal Cognitiva não é um produto separado. É a evolução cognitiva governada da mesma MEMORIA-PERMANENTE. A baseline de origem `0.29.3` permanece prova histórica válida; o pacote operacional atual é `0.31.0`, ainda sob `V5.5-PRIMARY` e `MEMORIA_PERMANENTE_CANONICAL_1.0`.

## 2. Estado vivo

```text
ORIGIN_BASELINE = 0.29.3 / PROVEN
CURRENT_PACKAGE = 0.31.0
RUNTIME_PROFILE = V5.5-PRIMARY
CURRENT_CLASS = UNIVERSAL_CONTEXT_MEMORY_INFRASTRUCTURE
TARGET_CLASS = UNIVERSAL_COGNITIVE_MEMORY_INFRASTRUCTURE
F01 = PROVEN_CURRENT
F02 = PROVEN_CURRENT / SHADOW
F03 = PROVEN_CURRENT / SHADOW
COGNITIVE_MISSION_PROVEN = NÃO
```

A classe alvo global não é promovida enquanto os gates remanescentes não forem implementados e comprovados.

## 3. Fundações e estado cognitivo

| Fundação / motor | Estado atual | Regra |
|---|---|---|
| Cognitive Kernel Contracts | PROVEN_CURRENT | contratos universais, default-off, fail-closed |
| Activation Engine | PROVEN_CURRENT / SHADOW | acessibilidade; não altera verdade |
| Priming Policy | PROVEN_CURRENT / SHADOW | trust/scope/budget/cap/TTL |
| Functional Salience | PROVEN_CURRENT / SHADOW | bounded/explainable; sem promoção de fato |
| Associative / Spreading Activation | PROVEN_CURRENT / SHADOW | Ontology + ExperienceGraph + pgvector; não reranqueia retrieval |
| Offline Consolidation | PLANNED | próximo escopo F04; não bloquear capture/retrieval |
| Reconsolidation | PLANNED | preservar versões |
| Concept Generalization | FOUNDATION_PRESENT / PLANNED | candidate before promotion |
| Prospective Memory | PLANNED | autorização antes de ação |
| Embodied / Sensorimotor | FOUNDATION_PRESENT / PLANNED | domínio digital primeiro |
| World Model | PLANNED | evidence/confidence/time/scope |
| Computational Forgetting | FOUNDATION_PRESENT / PLANNED | accessibility ≠ purge |
| Meta-memory | FOUNDATION_PRESENT / PLANNED | origem/confiança/conflito/explicação |

## 4. Persistência e migrations

A baseline `0.29.3` terminou em `0054_embedding_worker_role_login_normalization`. A evolução cognitiva comprovada aplicou, sem reutilização de número e com backups pré/pós-deploy:

```text
0055_cognitive_activation
0056_cognitive_salience
0057_cognitive_associative_memory
```

O banco canônico está em **57 migrations**, head `0057_cognitive_associative_memory`.

F03 adiciona somente estado derivado `SHADOW`:

- `memory_association_traversals`;
- `memory_association_candidates`.

As duas tabelas possuem `FORCE ROW LEVEL SECURITY`, são append-only e `memory_app` recebe somente `SELECT` direto; escrita acontece por função `SECURITY DEFINER` validada por tenant/scope.

## 5. F03 — Associative Memory / Spreading Activation

F03 implementa o fluxo executivo:

```text
seed memories
→ canonical neighbors
→ relation weight
→ hop decay
→ scope/security filter
→ conflict/evidence filter
→ bounded associative candidates
```

Fontes de evidência canônica realmente exercitadas na prova isolada:

- Ontology / `memory_knowledge_relations`;
- ExperienceGraph / nós e arestas ligados a memória;
- pgvector / similaridade de embeddings da versão atual.

Relações associativas suportadas: `SEMANTIC_SIMILARITY`, `TEMPORAL_PROXIMITY`, `CAUSAL_RELATION`, `SHARED_ENTITY`, `SHARED_PERSON`, `SHARED_OBJECTIVE`, `SHARED_CONTEXT`, `SHARED_OUTCOME`, `CO_OCCURRENCE`, `PROCEDURAL_DEPENDENCY`, `DECISION_DEPENDENCY`, `CONTRADICTION` e `SUPPORT`.

Limites hard-coded e validados: depth máximo 4, node budget máximo 256, time budget máximo/default 1000 ms, candidate budget máximo 128, proteção contra loops e trace determinístico. Timeout é fail-closed com `FAIL_CLOSED_NO_PARTIAL_CANDIDATES`.

## 6. Rollout e failure domain

F02 e F03 foram promovidas por rolling canary em `8790` mantendo `8787` saudável como fallback, e depois promovidas no primário `8787`.

Feature flags atuais:

```text
COGNITIVE_ACTIVATION
COGNITIVE_PRIMING
COGNITIVE_SALIENCE
COGNITIVE_ASSOCIATION
```

Todos os motores permanecem em `SHADOW`. Se associação falhar, o ContextEngine retorna o ranking lexical/semântico/state pré-existente; a falha fica no domínio assíncrono cognitivo. Nenhum candidato associativo é inserido no resultado canônico nesta fase.

## 7. Segurança, restart e recovery

Provas correntes demonstram:

- sete estruturas cognitivas com isolamento por tenant/RLS acumulado até F03 (cinco F02 + duas F03);
- least privilege e bloqueio de escrita direta em estruturas cognitivas;
- cross-tenant read/write isolado/bloqueado nas provas dedicadas;
- persistência F03 após novo interpretador e após restart real do canário;
- V5.5 conformance sem regressão em `8787` e `8790`;
- segurança HMAC/replay/capability preservada (`12/12 PASS` na prova live);
- backup criptografado pré e pós-deploy sem plaintext retido;
- restore pós-F03 com `pg_amcheck`, audit chain e erasure replay aprovados;
- recovery restaurado em head `0057_cognitive_associative_memory`.

Evidências da fase:

- `evidence/F03_ASSOCIATIVE_MEMORY_20260925.json` e `.md` — prova isolada multi-source;
- `evidence/F03_ASSOCIATIVE_BENCHMARK_20260925.json` — precision/recall e desempenho;
- `evidence/F03_CANONICAL_RUNTIME_PROOF_20260925.json` e `.md` — prova terminal do runtime canônico.

## 8. Gates cognitivos

| Gate | Estado |
|---|---|
| C0 Architecture Frozen | PROVEN |
| C1 Activation/Priming | PROVEN |
| C2 Salience | PROVEN |
| C3 Associative Memory | PROVEN |
| C4 Offline Consolidation | OPEN |
| C5 Reconsolidation | OPEN |
| C6 Concept Generalization | OPEN |
| C7 Prospective Memory | OPEN |
| C8 Embodied Memory | OPEN |
| C9 Universal Integration | OPEN |
| C10 Cognitive Recovery | OPEN |
| C11 Full Regression terminal | OPEN |
| C12 Cognitive MISSION_PROVEN | OPEN |

A prova de recovery executada em F03 é prova desta fase e da recuperabilidade da baseline atual; não antecipa C10, que deverá ser reexecutado sobre a arquitetura cognitiva completa.

## 9. Universalidade preservada

A evolução continua sem exigir GPT, OpenAI, Ollama, llama.cpp, CRM/ERP específico, Windows, um único consumidor ou inferência LLM no core.

## 10. Estado terminal desta reconciliação

```text
V5_5_RUNTIME = PROVEN_CURRENT
CURRENT_PACKAGE = 0.31.0
F01 = PROVEN_CURRENT
F02 = PROVEN_CURRENT / SHADOW
F03 = PROVEN_CURRENT / SHADOW
C0-C3 = PROVEN
C4-C12 = OPEN
NEXT_PHASE = F04_OFFLINE_CONSOLIDATION
COGNITIVE_MISSION_PROVEN = NÃO
```
