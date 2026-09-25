# RECONCILIAÇÃO CANÔNICA — V5.5 → MEMÓRIA UNIVERSAL COGNITIVA

## 1. Decisão arquitetural

A Memória Universal Cognitiva não é um produto separado. É a evolução cognitiva governada da mesma MEMORIA-PERMANENTE. A baseline de origem `0.29.3` permanece prova histórica válida; o pacote operacional atual é `0.30.0`, ainda sob `V5.5-PRIMARY` e `MEMORIA_PERMANENTE_CANONICAL_1.0`.

## 2. Estado vivo

```text
ORIGIN_BASELINE = 0.29.3 / PROVEN
CURRENT_PACKAGE = 0.30.0
RUNTIME_PROFILE = V5.5-PRIMARY
CURRENT_CLASS = UNIVERSAL_CONTEXT_MEMORY_INFRASTRUCTURE
TARGET_CLASS = UNIVERSAL_COGNITIVE_MEMORY_INFRASTRUCTURE
F01 = PROVEN_CURRENT
F02 = PROVEN_CURRENT / SHADOW
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
| Associative / Spreading Activation | PLANNED | próximo escopo F03 |
| Offline Consolidation | PLANNED | não bloquear capture/retrieval |
| Reconsolidation | PLANNED | preservar versões |
| Concept Generalization | FOUNDATION_PRESENT / PLANNED | candidate before promotion |
| Prospective Memory | PLANNED | autorização antes de ação |
| Embodied / Sensorimotor | FOUNDATION_PRESENT / PLANNED | domínio digital primeiro |
| World Model | PLANNED | evidence/confidence/time/scope |
| Computational Forgetting | FOUNDATION_PRESENT / PLANNED | accessibility ≠ purge |
| Meta-memory | FOUNDATION_PRESENT / PLANNED | origem/confiança/conflito/explicação |

## 4. Persistência e migrations

A baseline `0.29.3` terminou em `0054_embedding_worker_role_login_normalization`. F02 promoveu, com backup e prova de recuperação:

```text
0055_cognitive_activation
0056_cognitive_salience
```

O banco canônico está em 56 migrations, head `0056_cognitive_salience`. Novas migrations devem continuar a partir do estado real do repositório, sem reutilização de número e sem reescrever migration aplicada.

## 5. Rollout e failure domain

F02 foi promovida por rolling canary em `8790` com `8787` mantido saudável, depois promovida em `8787`. Os três controles cognitivos são habilitados apenas em `SHADOW` e permanecem separáveis por feature flags.

```text
COGNITIVE_ACTIVATION
COGNITIVE_PRIMING
COGNITIVE_SALIENCE
```

Se a camada cognitiva falhar, captura e retrieval V5.5 continuam sendo a autoridade. Nenhum motor F02 reranqueia ou promove conhecimento no release atual.

## 6. Segurança, restart e recovery F02

Provas correntes demonstram FORCE RLS nas cinco estruturas cognitivas, least privilege, bloqueio cross-scope, persistência após restart, V5.5 conformance sem regressão, segurança HMAC/replay/capability preservada e restore criptografado com `pg_amcheck`, audit chain e erasure replay aprovados.

Evidência terminal da fase: `evidence/F02_CANONICAL_RUNTIME_PROOF_20260925.json` e `.md`.

## 7. Gates cognitivos

| Gate | Estado |
|---|---|
| C0 Architecture Frozen | PROVEN |
| C1 Activation/Priming | PROVEN |
| C2 Salience | PROVEN |
| C3 Associative Memory | OPEN |
| C4 Offline Consolidation | OPEN |
| C5 Reconsolidation | OPEN |
| C6 Concept Generalization | OPEN |
| C7 Prospective Memory | OPEN |
| C8 Embodied Memory | OPEN |
| C9 Universal Integration | OPEN |
| C10 Cognitive Recovery | OPEN |
| C11 Full Regression terminal | OPEN |
| C12 Cognitive MISSION_PROVEN | OPEN |

A prova de recovery executada em F02 é uma prova da fase; não antecipa o gate terminal C10, que deverá ser reexecutado sobre a arquitetura cognitiva completa.

## 8. Universalidade preservada

A evolução continua sem exigir GPT, OpenAI, Ollama, llama.cpp, CRM/ERP específico, Windows, um único consumidor ou inferência LLM no core.

## 9. Estado terminal desta reconciliação

```text
V5_5_RUNTIME = PROVEN_CURRENT
CURRENT_PACKAGE = 0.30.0
F01 = PROVEN_CURRENT
F02 = PROVEN_CURRENT / SHADOW
NEXT_PHASE = F03_ASSOCIATIVE_MEMORY
COGNITIVE_MISSION_PROVEN = NÃO
```
