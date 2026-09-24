# Baseline MEMORIA-PERMANENTE 0.13.0

Data de consolidação: 2026-09-02 (horário de Brasília).

## Objetivo

Este documento define a primeira baseline Git limpa do repositório `C:\New Projet\MEMORIA-PERMANENTE`. Ele registra o estado que pode ser reproduzido a partir de fonte versionada sem incluir runtime, backups ou credenciais.

## Componentes da baseline

- API/serviço `memoria-permanente` 0.13.0.
- Schema PostgreSQL `memory-0.13.0` com migrations `0001` a `0014`.
- PostgreSQL 18.6 homologado e pgvector 0.8.6.
- Canonical Mutation Service obrigatório para mutações persistentes.
- Sanitização recursiva de payloads persistentes e cofre externo.
- Autenticação HMAC/capabilities no canal geral, RLS e isolamento multiagente.
- Versionamento, validação version-bound e invalidation de confiança após revisão.
- Learning Policy `LP-1.0.0` e Outcome Learning por versão.
- Session continuity/rotation, backup/recovery e provas históricas mantidas em `evidence/`.

## MEMORIA PLUS consolidada

`01`, `02`, `03` e `04` estão `PROVEN` e possuem validação ligada ao hash exato da versão correspondente no Memory Core.

Os itens `05`–`18` continuam abertos. Em especial, a autenticação especial legada de `/v1/governor/*` ainda deve ser removida/unificada pelo contrato universal antes do fechamento global da V4.

## Política de repositório

Itens operacionais deliberadamente fora do Git:

- `.venv/`
- `runtime/`
- `backups/`
- `build/` e `dist/`
- logs, dumps e caches
- chaves, certificados privados e arquivos de credencial

Artefatos transitórios de implementação (`patch_*`, versões `.pre-*` e pacotes de integração antigos) foram preservados localmente em `runtime/baseline-archive-20260902/`, portanto permanecem fora da baseline sem serem destruídos.

## Critérios de aceitação desta baseline

1. `python -m compileall` dos módulos vigentes sem erro.
2. `pytest`: 53/53 PASS.
3. Audit chain íntegra após o reseal histórico, sem `strict_errors` no epoch atual.
4. API saudável em 0.13.0.
5. Nenhum caminho `.venv/`, `runtime/` ou `backups/` versionado.
6. Varredura de segredo sem chave/token real detectado no conjunto versionável; ocorrências sintéticas de testes e padrões do sanitizer são permitidas e classificadas.
7. Working tree limpo após o commit.

## Estado de missão

Esta baseline é um ponto seguro de desenvolvimento, não uma declaração de conclusão integral da V4.

`V4_FULL_PROVEN = NÃO`
`MISSION_PROVEN = NÃO`
