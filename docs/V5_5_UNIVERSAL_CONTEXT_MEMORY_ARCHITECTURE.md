# MEMÓRIA PERMANENTE V5.5 — ARQUITETURA UNIVERSAL DE MEMÓRIA E CONTEXTO

**Data da decisão:** 06/09/2026  
**Status:** APROVADO COMO DIREÇÃO CANÔNICA DE ARQUITETURA  
**Implementação/runtime comprovado no momento do registro:** V5.3-PRIMARY / Windows JNS  
**Contrato universal V5.5:** `MEMORIA_PERMANENTE_UNIVERSAL_PRODUCT_V2`

## Decisão soberana aprovada

> A Memória Permanente sempre atende um ou mais sistemas consumidores, mas permanece produto independente. Pode ser instalada junto do consumidor, em outra máquina, em servidor próprio ou como serviço compartilhado.

Essa regra passa a governar a evolução V5.5.

A Memória Permanente não é um submódulo de OpenAI, de qualquer outra IA, de WhatsApp, Market Intelligence, Marketing Intelligence, LMCP, WMCP, Windows, Linux ou de qualquer consumidor específico. Ela é infraestrutura independente de memória, contexto, estado, continuidade e aprendizado.

IA é uma capacidade e uma classe de consumidor. Não é requisito para o funcionamento do núcleo.

## Classe técnica V5.5

```text
UNIVERSAL_CONTEXT_MEMORY_INFRASTRUCTURE
```

Escopo funcional:

```text
MEMÓRIA
CONTEXTO
ESTADO
HISTÓRICO
DECISÕES
EVENTOS
EVIDÊNCIAS
CHECKPOINTS
APRENDIZADO
CONTINUIDADE
```

## Consumidores-alvo

A mesma Memória Permanente deve poder atender, por contratos públicos e isolamento explícito:

- IAs e agentes: GPT, Claude, Gemini, modelos locais e futuros provedores;
- sistemas conversacionais: WhatsApp API, atendimento, vendas, chat e CRM;
- sistemas de inteligência: Market Intelligence, Marketing Intelligence e produtos analíticos;
- infraestrutura e orquestração: LMCP, WMCP e equivalentes;
- aplicações tradicionais: ERP, CRM, marketplace, SaaS e sistemas sem IA;
- consumidores futuros que cumpram o contrato universal e os gates de conformidade.

## Perfis de implantação

A identidade do produto não muda conforme o local da implantação.

```text
CO_LOCATED
  Memória e consumidor no mesmo host.

DEDICATED_HOST
  Memória em outra máquina ou servidor controlado.

SHARED_SERVICE
  Uma instância governada atendendo múltiplos consumidores isolados.

DISTRIBUTED_HA
  Evolução para alta disponibilidade/distribuição sem alterar o contrato do consumidor.
```

## Perfis de capacidade

O produto permanece único, mas ativa apenas o necessário para cada caso:

```text
CORE
  persistência + contexto + estado + segurança

CONVERSATIONAL
  contexto de conversa + continuidade de sessão + contexto de cliente

AI
  provider adapters + embeddings + recuperação semântica + sugestões de IA

OPERATIONAL
  checkpoint + resume + recovery + estado operacional

INTELLIGENCE
  aprendizado + experiência + procedimentos + conhecimento

FULL
  CORE + CONVERSATIONAL + AI + OPERATIONAL + INTELLIGENCE
```

Nenhum perfil pode furar as políticas soberanas, ACL, isolamento, provenance, lifecycle, auditoria ou segurança do Memory Core.

# OITO PONTOS DE FECHAMENTO DA V5.5

## 1. DNA UNIVERSAL DEFINITIVO

A Memória Permanente deve possuir identidade estável e independente de:

- sistema operacional;
- host;
- branch;
- consumidor;
- provedor de IA;
- projeto específico.

Runtime comprovado não redefine a identidade do produto.

## 2. CONTRATO UNIVERSAL DE CONSUMIDOR

Qualquer consumidor deve integrar somente por contrato público governado, incluindo conforme aplicabilidade:

```text
memory.capture
memory.context
memory.search
memory.checkpoint
memory.resume
memory.state
```

Transportes homologados permanecem REST/HTTPS, OpenAPI e MCP. Acesso direto ao PostgreSQL por consumidores externos continua proibido.

## 3. PERFIS DE IMPLANTAÇÃO

Devem existir contratos e documentação para, no mínimo:

- instalação junto ao consumidor;
- instalação em host dedicado;
- serviço compartilhado multi-consumidor;
- evolução para alta disponibilidade/distribuição.

A movimentação entre perfis não pode obrigar mudança de domínio do consumidor.

## 4. PERFIS DE CAPACIDADE

IA, embeddings, reranker, agentes e outros componentes pesados são opcionais e ativados somente quando o caso de uso justificar.

Um WhatsApp API simples pode usar somente CORE + CONVERSATIONAL. Um sistema complexo de agentes pode usar FULL.

## 5. ADAPTERS OFICIAIS

A arquitetura deve manter uma fronteira de adapters oficiais para tipos de consumidor e provedores, incluindo:

- REST/OpenAPI;
- MCP;
- Memory Client Adapter;
- AI Integration Adapter;
- provider adapters de IA quando necessários;
- adapters conversacionais/WhatsApp quando homologados;
- futuros adapters por contrato versionado.

Adapter traduz integração; não governa nem substitui o Memory Core.

## 6. ISOLAMENTO UNIVERSAL

A hierarquia soberana permanece:

```text
GLOBAL_USER
  -> PROJECT
      -> MISSION
          -> SESSION
```

Nenhuma similaridade semântica, adapter ou consumidor pode atravessar escopo sem autorização/política explícita. Uma instância compartilhada deve impedir vazamento entre projetos, usuários, tenants e sistemas.

## 7. KIT DE CONFORMIDADE

Um consumidor novo não é declarado compatível apenas porque conseguiu fazer uma chamada HTTP.

O kit de conformidade V5.5 deve comprovar, quando aplicável:

- captura;
- recuperação correta de contexto;
- isolamento positivo e negativo;
- autenticação/autorização;
- idempotência;
- checkpoint/resume;
- restart/recovery;
- ausência de acesso direto ao banco;
- regressão de segurança;
- integridade e auditoria.

## 8. PORTABILIDADE COMPROVADA

Portabilidade é requisito de prova, não somente desenho.

Estado no momento desta decisão:

```text
Windows JNS
  runtime de produção atualmente comprovado

Linux
  desenvolvimento / CI / build / sincronização;
  runtime de produção ainda deve ser homologado e provado

Outros ambientes
  somente podem ser declarados suportados depois de prova equivalente
```

A V5.5 deve ampliar a matriz de runtime homologado sem transformar qualquer plataforma em identidade do produto.

# REGRAS DE SEGURANÇA E SOBERANIA PRESERVADAS

A V5.5 não revoga as garantias anteriores. Permanecem obrigatórios:

- Memory Core soberano;
- PostgreSQL como fonte canônica conforme baseline aplicável;
- consumidores sem acesso direto ao banco;
- IA externa sem escrita soberana direta;
- sugestões de IA submetidas a normalização, sanitização, política, aceitação e auditoria;
- lifecycle governado;
- retenção/holds/quarentena antes de purge quando aplicável;
- versionamento e provenance;
- segregação de escopo;
- criptografia, segredo fora da memória canônica e credenciais escopadas;
- backup, restore e recuperação;
- testes de segurança, regressão e recuperação antes de promoção.

# REGRA DE NÃO CONFUSÃO DE VERSÃO

Este documento aprova a **arquitetura V5.5**.

Não significa que todos os runtimes, migrations, pacotes e integrações da V5.5 já estejam implementados ou homologados. Enquanto a implementação completa não for provada, a baseline operacional comprovada continua sendo declarada separadamente.

```text
ARQUITETURA APROVADA: V5.5
RUNTIME COMPROVADO NO REGISTRO: V5.3-PRIMARY / Windows JNS
```

A V5.5 somente poderá ser declarada operacionalmente concluída quando seus oito pontos forem implementados, testados e comprovados por evidência técnica.
