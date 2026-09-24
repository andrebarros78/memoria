# V5.2-RC1 Controlled Deployment Evidence

Status: V5.2_RC1_API_DB_DEPLOYED_WITH_OBSERVABILITY_BLOCKER

- Branch: v5.2-rebase-acquisitions-20260904
- HEAD: 1791965cfdd651864ed1eb98acb4d5d5460a3f61
- V4 baseline preserved: c77686471dbec0b53002b8d2653cf7dcb90b658f
- V4 API: 8787 health=ok
- RC1 API: 8792 health=ok
- RC1 DB: memoria_permanente_v52_rc1
- Retrieval traces: V4=95, RC1=97
- Unauthenticated context call: 401 observed
- Signed context no-hit: 200, trace persisted only in RC1
- Signed context hit: selected_count=1, modes=LEXICAL+SEMANTIC
- Pytest: 178 passed
- Defender project threats: 0
- Rollback script: deploy/v5.2-rc1/rollback.ps1
- Phoenix RC1: BLOCKED; 6007/4318 not listening after bootstrap window

Promotion allowed: false until Phoenix RC1 or approved observability fallback is validated.
