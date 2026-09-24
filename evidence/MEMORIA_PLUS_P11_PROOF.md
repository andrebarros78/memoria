# MEMORIA PLUS P11 — GLOBAL_USER como escopo canônico

- Resultado: **PASS**
- Schema: `memory-0.19.0`
- Memory Scope: `MS-1.0.0`
- Legado classificado como GLOBAL_USER: `1186`
- Checks: `40/40`

## Separação canônica

- `memory_scope = GLOBAL_USER|PROJECT|MISSION|SESSION` — contexto semântico.
- `sharing_scope = PRIVATE_USER|PROJECT_SHARED|AGENT_PRIVATE|AGENT_TEAM|ORGANIZATION_SHARED|SYSTEM_SHARED` — ACL.
- `Memória Geral` permanece somente label humano de `GLOBAL_USER`.
- O RLS continua baseado em `sharing_scope`; `memory_scope` não concede acesso.

## Checks

- [x] `api_0_19_0`
- [x] `scope_spec_requires_auth`
- [x] `scope_spec_version`
- [x] `exact_four_semantic_scopes`
- [x] `global_user_is_canonical`
- [x] `general_memory_is_human_label_only`
- [x] `sharing_code_rejected_as_memory_scope`
- [x] `global_user_rejected_as_sharing_scope`
- [x] `project_requires_reference`
- [x] `global_user_forbids_reference`
- [x] `create_global_scope`
- [x] `create_project_scope`
- [x] `create_mission_scope`
- [x] `create_session_scope`
- [x] `list_global_scope_exact`
- [x] `list_project_scope_exact`
- [x] `list_mission_scope_exact`
- [x] `list_session_scope_exact`
- [x] `list_ref_requires_scope`
- [x] `context_without_selector_is_global_user_only`
- [x] `mission_context_adds_mission_scope`
- [x] `session_context_adds_session_scope`
- [x] `project_context_adds_project_scope`
- [x] `combined_context_resolves_all_four_scopes`
- [x] `semantic_scope_and_sharing_acl_independent`
- [x] `schema_version`
- [x] `memory_scope_schema_version`
- [x] `canonical_global_meta`
- [x] `legacy_backfill_exact`
- [x] `all_persisted_scopes_canonical`
- [x] `memory_scope_columns_enforced`
- [x] `rls_acl_uses_sharing_not_semantic_scope`
- [x] `memory_items_force_rls`
- [x] `db_context_match_function_exact`
- [x] `migration_0026_checksum`
- [x] `schema_invalid_scope_rejected`
- [x] `schema_global_ref_rejected`
- [x] `semantic_scope_immutable`
- [x] `conversation_ingestion_uses_session_semantic_scope`
- [x] `session_rotation_uses_session_semantic_scope`
