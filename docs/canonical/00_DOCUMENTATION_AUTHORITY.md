# AUTORIDADE DOCUMENTAL CANÔNICA — MEMORIA-PERMANENTE

**Estado:** CANÔNICO
**Baseline de origem comprovada:** `0.29.3` / `V5.5-PRIMARY`
**Pacote operacional atual:** `0.31.0` / `V5.5-PRIMARY`
**Release:** `MEMORIA_PERMANENTE_CANONICAL_1.0`

## Regra de autoridade

Quando houver conflito documental, aplicar esta ordem:

1. runtime vivo + testes + evidências técnicas atuais;
2. baseline canônica V5.5 comprovada;
3. contrato/doutrina de Memória Universal;
4. projeto executivo da Memória Universal Cognitiva, como evolução planejada;
5. documentos históricos V4/V5/V5.1/V5.2/V5.3 e gates antigos, somente para rastreabilidade.

Nenhum documento de arquitetura futura pode converter uma capacidade planejada em capacidade operacional.

## Estados documentais

- `PROVEN_CURRENT`: implementado, integrado, testado e comprovado no runtime atual.
- `CURRENT_CONTRACT`: contrato vigente do produto.
- `FOUNDATION_PRESENT`: fundação técnica existente, mas capacidade cognitiva completa ainda não implementada.
- `PLANNED`: especificado para evolução, ainda não comprovado.
- `EXTERNAL_OPTIONAL`: integração externa que não pertence ao core.
- `LEGACY_HISTORICAL`: preservado apenas para histórico.
- `OUT_OF_SCOPE`: não é objetivo do produto.

## Identidade atual

```text
Produto: MEMORIA-PERMANENTE
Versão: 0.31.0
Runtime: V5.5-PRIMARY
Release: MEMORIA_PERMANENTE_CANONICAL_1.0
Classe atual: UNIVERSAL_CONTEXT_MEMORY_INFRASTRUCTURE
```

A classe alvo da evolução cognitiva é `UNIVERSAL_COGNITIVE_MEMORY_INFRASTRUCTURE`, mas ela não substitui a classe atual antes da conclusão e prova dos gates cognitivos C0–C12.

## Evolução cognitiva comprovada até F03

- F01 — Cognitive Kernel Contracts: `PROVEN_CURRENT`;
- F02 — Activation / Priming / Salience: `PROVEN_CURRENT / SHADOW`;
- F03 — Associative Memory / Spreading Activation: `PROVEN_CURRENT / SHADOW`.

F03 usa Ontology, ExperienceGraph e pgvector como evidência canônica para acessibilidade associativa derivada. Associação inferida não é promovida a verdade canônica e não reranqueia retrieval no modo atual.

## IA e providers

A partir da baseline `0.29.3`, inferência concreta OpenAI, Ollama e llama.cpp não pertence ao core. Os adapters concretos históricos foram movidos para `legacy/provider_integrations`. O core mantém `AI_INTEGRATION` como fronteira governada para sugestões externas.

Logo, OpenAI/Ollama/llama.cpp não devem ser classificados como capacidades pendentes do core. São integrações externas opcionais fora do critério de conclusão do produto.

## Regra terminal

`MISSION_PROVEN` permanece válido para o escopo comprovado da baseline canônica V5.5. A Memória Universal Cognitiva é um novo escopo; embora C0–C3 estejam comprovados, `COGNITIVE_MISSION_PROVEN = NÃO` enquanto C4–C12 permanecerem abertos.
