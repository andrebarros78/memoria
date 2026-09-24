# MEMORY <-> GOVERNOR CONTRACT V1

**Contract version:** 1.0.0
**Status:** FROZEN / PROVEN
**Gate:** `MEMORY_GOVERNOR_CONTRACT_PROVEN`

## Sovereign rule

The Governor does not consume general history. It receives only consolidated, validated and explicitly eligible PROJECT memory for the project to which it is immutably bound.

Mission state is delivered through a separate operational channel and is never mixed with PROJECT memory recall.

## Mandatory boundary

```text
MEMORY PERMANENT
  GLOBAL              -> BLOCKED FOR GOVERNOR
  PROJECT              -> ALLOWED ONLY WHEN VALIDATED + GOVERNOR_ELIGIBLE
  MISSION MEMORY       -> NOT PART OF PROJECT MEMORY RECALL
  SESSION / CHAT       -> BLOCKED FOR GOVERNOR

PROJECT MEMORY CHANNEL -> durable project knowledge
MISSION STATE CHANNEL  -> current execution/checkpoint
```

## Binding

Every Governor connection is bound to exactly one `project_id` by:

- `tenant_id`
- `governor_id`
- `project_id`
- `contract_version`
- governed access-key hash

`Governor -> Project` rebinding is forbidden by application policy and by a PostgreSQL trigger.

## Eligible project memory

A memory is visible to a Governor only when all conditions are true:

- `sharing_scope = PROJECT_SHARED`
- `project_id = bound project_id`
- `validation_status = VALIDATED`
- `governor_eligible = true`
- category belongs to the approved durable-knowledge allowlist
- operator state is `ATIVA`, `PERMANENTE` or `PROTEGIDA`
- lifecycle is not `DELETE_ELIGIBLE`, `QUARANTINED` or `PURGED`

Global/system-shared memories, other projects, unvalidated memories, hypotheses and session/chat noise do not enter Governor context.

## Mission state

The Governor can read/write only the operational checkpoint for its bound project through `/v1/governor/missions/{mission_id}/...`.

Mission checkpoint updates explicitly declare:

- `memory_promotion = false`
- `project_memory_write = false`

A mission result becomes durable PROJECT memory only through the separate governed validation/promotion pipeline.

## Fail-closed

Any of the following is denied:

- missing Governor identity
- invalid access key
- wrong project
- wrong contract version
- Governor rebind attempt
- generic memory read/write by an identified Governor
- generic context retrieval by an identified Governor
- generic checkpoint API by an identified Governor
- generic session API by an identified Governor

## Public Governor contract

- `GET /v1/governor/contract`
- `GET /v1/governor/project-context`
- `GET /v1/governor/missions/{mission_id}/state`
- `POST /v1/governor/missions/{mission_id}/checkpoint`

The Governor has no direct PROJECT-memory write endpoint.

## Proof

Canonical evidence:

- `evidence/MEMORY_GOVERNOR_CONTRACT_PROOF.json`
- `evidence/MEMORY_GOVERNOR_CONTRACT_PROOF.md`

Required terminal state:

`MEMORY_GOVERNOR_CONTRACT_PROVEN = PASS`
## Estado de implantação

**Estado atual:** `STAGED_ONLY / NOT_INSTALLED_IN_GOVERNOR`

O contrato está implementado e disponível no lado da MEMORIA-PERMANENTE, porém não está instalado nem ativado no GOVERNADOR.

A instalação no GOVERNADOR somente poderá ocorrer após a finalização e aprovação da `MEMORIA_PERMANENTE_IA_SISTEMAS_V5.1`, mediante autorização operacional específica.

Até essa autorização:

- não deve existir binding ativo do Governador real;
- não deve existir credencial do contrato no GOVERNADOR;
- o GOVERNADOR permanece com sua integração anterior;
- os artefatos de integração futura permanecem somente em `future-install/MEMORY_GOVERNOR_CONTRACT_V1/`;
- arquivos de staging não podem ser copiados ou ativados no GOVERNADOR.
