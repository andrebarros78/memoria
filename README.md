# MEMORIA-PERMANENTE

Módulo soberano externo e infraestrutura universal de memória, contexto, estado, continuidade e aprendizado do projeto `MEMORIA_PERMANENTE_IA_SISTEMAS`.

## Baseline vigente

- Produto universal: **MEMORIA-PERMANENTE**.
- Produto/API da arvore canonica atual: 0.32.0.
- Marco funcional operacional comprovado: `V5.5`.
- Arquitetura canônica operacional comprovada: `V5.5`.
- Contrato universal: `MEMORIA_PERMANENTE_UNIVERSAL_PRODUCT_V2`.
- Classe técnica V5.5: `UNIVERSAL_CONTEXT_MEMORY_INFRASTRUCTURE`.
- Runtime operacional comprovado atual: **Windows JNS** em `C:\New Projet\MEMORIA-PERMANENTE`.
- Desenvolvimento, CI, build, comparação e sincronização: **Linux**, quando explicitamente sincronizado e provado.
- Schema/migration head da arvore canonica atual: 0058_cognitive_offline_consolidation (58 migrations numeradas; equivalencias historicas 0030z/0032z preservadas).
- AI Integration Adapter: `V5.3_AI_INTEGRATION_ADAPTER`.
- IA obrigatória para o núcleo: **NÃO**.
- Purge direto: desabilitado por desenho.
- `MISSION_PROVEN`: **SIM**, para a V5.5 no runtime Windows comprovado, com conformidade, segurança e restart/recovery validados.

A prova histórica da baseline V5.3 está em `evidence/BASELINE_0_28_0_PROOF.md` e `evidence/V5_3_AI_INTEGRATION_ADAPTER_PROOF_20260904.md`. A prova viva V5.5 está em `evidence/MEMORIA_PERMANENTE_CANONICAL_1_0_LIVE_RUNTIME_PROOF.json`. Runtime comprovado não redefine a identidade do produto.

## Decisão arquitetural V5.5

Decisão aprovada em 06/09/2026:

> **A Memória Permanente sempre atende um ou mais sistemas consumidores, mas permanece produto independente. Pode ser instalada junto do consumidor, em outra máquina, em servidor próprio ou como serviço compartilhado.**

A V5.5 consolida a Memória Permanente como infraestrutura universal. IA passa a ser uma capacidade opcional e uma classe de consumidor, nunca dependência estrutural do Memory Core.

A V5.5 fecha oito pontos obrigatórios:

1. DNA universal definitivo;
2. contrato universal de consumidor;
3. perfis de implantação;
4. perfis de capacidade;
5. adapters oficiais;
6. isolamento universal;
7. kit de conformidade;
8. portabilidade comprovada.

Documento canônico: `docs/V5_5_UNIVERSAL_CONTEXT_MEMORY_ARCHITECTURE.md`.
Manifesto legível por máquina: `.wmcp/architecture-v5.5.json`.

## Contrato de produto universal

A Memória Permanente é um **produto universal de memória e contexto persistentes**, não um submódulo de Windows, Linux, Market Intelligence, WhatsApp, LMCP, WMCP ou qualquer motor de IA. O runtime pode ser comprovado em uma plataforma específica; a identidade do produto permanece estável e universal.

Regras obrigatórias:

- Windows JNS = runtime-alvo comprovado nesta baseline.
- Linux = ambiente de desenvolvimento/CI/sincronização, não cópia principal enquanto não for promovido e provado como runtime de produção equivalente.
- Market Intelligence = consumidor externo autorizado, não dono da memória.
- WhatsApp/API e sistemas conversacionais = consumidores elegíveis por contratos de contexto/memória, não donos da memória.
- WMCP/LMCP = orquestradores/consumidores autorizados, não identidade da memória.
- IA externa = fonte governada de sugestões quando utilizada, sem escrita direta e sem acesso direto ao banco.
- O núcleo deve funcionar sem chave ou provedor de IA externo.
- Product DNA e `product_id` permanecem independentes de branch, runtime, host ou consumidor.
- Endpoint público de contrato: `/v1/product-universality`.

## Perfis V5.5

Perfis de implantação:

- `CO_LOCATED`: Memória e consumidor no mesmo host.
- `DEDICATED_HOST`: Memória em outra máquina ou servidor controlado.
- `SHARED_SERVICE`: uma instância governada atendendo múltiplos consumidores isolados.
- `DISTRIBUTED_HA`: evolução para alta disponibilidade sem mudar o contrato do consumidor.

Perfis de capacidade:

- `CORE`: persistência, contexto, estado e segurança.
- `CONVERSATIONAL`: contexto de conversa, sessão e cliente.
- `AI`: provider adapters, embeddings, recuperação semântica e sugestões de IA.
- `OPERATIONAL`: checkpoint, resume, recovery e estado operacional.
- `INTELLIGENCE`: aprendizado, experiência, procedimentos e conhecimento.
- `FULL`: composição de todos os perfis.

## Arquitetura vigente

A Memória Permanente é independente do WMCP Core e de consumidores específicos. A integração ocorre por contratos públicos REST/OpenAPI/MCP e pelo Memory Client Adapter universal quando aplicável.

Controles estruturais presentes incluem PostgreSQL/RLS, autenticação HMAC com anti-replay e capabilities, sessões curtas de navegador somente leitura, cofre externo com DPAPI no Windows, proteção de chaves por provider de plataforma para desenvolvimento POSIX, Canonical Mutation Service, sanitização de payloads persistentes, versionamento append-only, validação ligada a versão/hash, pgvector, Outcome Learning por versão, lifecycle governado, legal erasure, backup criptografado e observabilidade V5.2.

## MEMORIA PLUS

A fila de evolução e suas provas históricas permanecem preservadas em `docs/` e `evidence/`. O estado de uma prioridade somente deve ser considerado comprovado quando acompanhado da respectiva evidência técnica e dos hashes aplicáveis.

## Segurança de repositório e runtime

Nunca versionar `.venv`, `runtime`, `backups`, bancos, modelos, logs ou material de chave. Segredos operacionais pertencem a stores externos ao repositório, como `%ProgramData%\MemoriaPermanente` no Windows.

O purge direto permanece proibido. Exclusão destrutiva somente pode ocorrer pelo lifecycle/erasure governado e pelos respectivos gates.

## Critério de conclusão

Código gerado, testes unitários isolados ou uma baseline histórica não bastam para conclusão. O produto só pode receber `MISSION_PROVEN` depois de regressão, segurança, integração, persistência, concorrência, backup/restore, restart/recovery, integridade e gates finais aplicáveis terem sido executados e comprovados.

A V5.5 está implementada e comprovada no runtime Windows canônico. Evoluções posteriores continuam subordinadas aos mesmos gates de regressão, segurança, integração, persistência, recovery e integridade.

## Governança atual de runtime V5.5

- Branch canônica de fonte: `canonical/memoria-permanente-1.0-reconciled`.
- Versão da API/pacote: `0.32.0`.
- Runtime profile: `V5.5-PRIMARY`.
- Release channel: `MEMORIA_PERMANENTE_CANONICAL_1.0`.
- Runtime Windows: `C:\New Projet\MEMORIA-PERMANENTE`.
- Fonte Git canônica: `C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0`.
- Prova viva: `evidence/MEMORIA_PERMANENTE_CANONICAL_1_0_LIVE_RUNTIME_PROOF.json`.

## Governança histórica de runtime V5.3

Estado corrigido em 2026-09-05:

- Branch operacional local: `v5.3-primary-20260904`.
- Tag de baseline operacional: `baseline-0.28.1`.
- Versão da API: `0.28.1`.
- Runtime profile: `V5.3-PRIMARY`.
- Release channel: `v5.3-primary-promoted`.
- Adapter de integração: `V5.3_AI_INTEGRATION_ADAPTER`.
- Banco principal atual: `memoria_permanente_v52_primary`.
- Migrations ativas: `0040` até `0051`.

Regra de auditoria:

- Auditar funcionalidade/recovery/segurança em execução no runtime comprovado atual.
- Auditar portabilidade, empacotamento e CI sem transformar uma cópia Linux em identidade do produto.
- Qualquer consumidor externo deve operar por contrato público, credencial escopada e gates da memória.
- Nenhuma branch, host ou sistema consumidor pode reclassificar a Memória Permanente como produto não universal.
