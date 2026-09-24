# ADDENDUM CANÃ”NICO â€” V5.5 / 0.29.3

**Este documento nÃ£o apaga nem altera a evidÃªncia terminal anterior.** Ele registra a evoluÃ§Ã£o posterior da baseline canÃ´nica para `0.29.3` e deve ser lido em conjunto com `docs/canonical/`.

## Estado atual

```text
Produto: MEMORIA-PERMANENTE
VersÃ£o: 0.29.3
Runtime: V5.5-PRIMARY
Release: MEMORIA_PERMANENTE_CANONICAL_1.0
V5_5_BASELINE: PROVEN_CURRENT
```

## AlteraÃ§Ã£o arquitetural consolidada

InferÃªncia concreta de LLM deixou de pertencer ao core.

Foram retirados do pacote canÃ´nico:

- `OpenAIProviderAdapter`;
- `OllamaProviderAdapter`;
- `LlamaCppProviderAdapter`;
- flags/credenciais/endpoints/portas especÃ­ficas de inferÃªncia desses engines no core;
- gates histÃ³ricos que tratavam troca de provider como prova terminal do produto.

O material histÃ³rico foi preservado em `legacy/provider_integrations/`.

A fronteira vigente Ã©:

```text
IA externa â†’ AI_INTEGRATION â†’ polÃ­ticas/gates â†’ memÃ³ria soberana
```

Logo, OpenAI/Ollama/llama.cpp nÃ£o pertencem Ã  lista de capacidades `NÃƒO COMPROVADAS` do core.

## Provas pÃ³s-alteraÃ§Ã£o

- full regression: `340 passed`, `2 POSIX-only skipped`, `0 failed`;
- seguranÃ§a focada: `101/101 passed`;
- Ruff: PASS;
- compileall: PASS;
- isolated pip check: PASS;
- V5.5 live runtime: PASS;
- `conformance_compatible=true`;
- `restart_recovery_verified=true`;
- Agent+Skill E2E: PASS;
- `restart_verified=true`.

Wheel:

```text
memoria_permanente-0.29.3-py3-none-any.whl
SHA-256: bb7e7a5ab0d0116706cf4f293f31c42eb53592cb239c3c97a3b14227272f29cc
```

CÃ³digo validado:

```text
7088f09a92a76b34921872ba29cacc17f7e50818
```

## RelaÃ§Ã£o com MemÃ³ria Universal Cognitiva

A baseline V5.5 continua comprovada. A evoluÃ§Ã£o cognitiva Ã© um novo escopo e permanece `PLANNED` atÃ© implementaÃ§Ã£o e prova de seus gates.

```text
V5_5_MISSION_PROVEN = SIM, no escopo jÃ¡ comprovado
COGNITIVE_MISSION_PROVEN = NÃƒO
```

NÃ£o hÃ¡ contradiÃ§Ã£o entre os dois estados: a missÃ£o cognitiva estende a baseline sem retroativamente alterar o que foi provado.
