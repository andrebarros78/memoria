# AUTORIDADE DOCUMENTAL CANÃ”NICA â€” MEMORIA-PERMANENTE

**Estado:** CANÃ”NICO  
**Baseline operacional:** `0.29.3` / `V5.5-PRIMARY`  
**Release:** `MEMORIA_PERMANENTE_CANONICAL_1.0`

## Regra de autoridade

Quando houver conflito documental, aplicar esta ordem:

1. runtime vivo + testes + evidÃªncias tÃ©cnicas atuais;
2. baseline canÃ´nica V5.5 comprovada;
3. contrato/doutrina de MemÃ³ria Universal;
4. projeto executivo da MemÃ³ria Universal Cognitiva, como evoluÃ§Ã£o planejada;
5. documentos histÃ³ricos V4/V5/V5.1/V5.2/V5.3 e gates antigos, somente para rastreabilidade.

Nenhum documento de arquitetura futura pode converter uma capacidade planejada em capacidade operacional.

## Estados documentais

- `PROVEN_CURRENT`: implementado, integrado, testado e comprovado no runtime atual.
- `CURRENT_CONTRACT`: contrato vigente do produto.
- `FOUNDATION_PRESENT`: fundaÃ§Ã£o tÃ©cnica existente, mas capacidade cognitiva completa ainda nÃ£o implementada.
- `PLANNED`: especificado para evoluÃ§Ã£o, ainda nÃ£o comprovado.
- `EXTERNAL_OPTIONAL`: integraÃ§Ã£o externa que nÃ£o pertence ao core.
- `LEGACY_HISTORICAL`: preservado apenas para histÃ³rico.
- `OUT_OF_SCOPE`: nÃ£o Ã© objetivo do produto.

## Identidade atual

```text
Produto: MEMORIA-PERMANENTE
VersÃ£o: 0.29.3
Runtime: V5.5-PRIMARY
Release: MEMORIA_PERMANENTE_CANONICAL_1.0
Classe atual: UNIVERSAL_CONTEXT_MEMORY_INFRASTRUCTURE
```

A classe alvo da evoluÃ§Ã£o cognitiva Ã© `UNIVERSAL_COGNITIVE_MEMORY_INFRASTRUCTURE`, mas ela nÃ£o substitui a classe atual antes da conclusÃ£o e prova dos gates cognitivos.

## IA e providers

A partir da versÃ£o `0.29.3`, inferÃªncia concreta OpenAI, Ollama e llama.cpp nÃ£o pertence ao core. Os adapters concretos histÃ³ricos foram movidos para `legacy/provider_integrations`. O core mantÃ©m `AI_INTEGRATION` como fronteira governada para sugestÃµes externas.

Logo, OpenAI/Ollama/llama.cpp nÃ£o devem ser classificados como `NÃƒO COMPROVADOS` do core. SÃ£o integraÃ§Ãµes externas opcionais fora do critÃ©rio de conclusÃ£o do produto.

## Regra terminal

`MISSION_PROVEN` permanece vÃ¡lido para o escopo comprovado da baseline canÃ´nica V5.5. A MemÃ³ria Universal Cognitiva Ã© um novo escopo e inicia com `COGNITIVE_MISSION_PROVEN = NÃƒO`.
