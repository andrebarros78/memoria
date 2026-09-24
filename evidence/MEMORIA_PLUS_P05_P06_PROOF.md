# MEMORIA PLUS P05/P06 PROOF

**Result:** PASS

- Universal Adapter: 1.1.0
- Legacy unsigned: HTTP 401
- Legacy X-Governor-Key only: HTTP 401
- Legacy route with valid universal auth: HTTP 404
- V1 stale artifact types: CHECKPOINT, CONTEXT_PACK, EMBEDDING, RETRIEVAL_TRACE, SESSION_CHECKPOINT
- V2 ready embeddings: 1
- Schema: memory-0.14.2

## Checks
- api_0_14_2: PASS
- universal_adapter_1_1: PASS
- legacy_unsigned_401: PASS
- legacy_governor_key_not_auth_401: PASS
- legacy_signed_route_removed_404: PASS
- no_active_governor_auth_source: PASS
- all_required_artifact_types_ready_before_revision: PASS
- all_required_artifact_types_stale_after_revision: PASS
- stale_bound_to_v1: PASS
- state_transition_events_recorded: PASS
- db_invalidation_trigger_active: PASS
- v2_embedding_ready: PASS
- v2_embedding_depends_on_v2: PASS
- schema_0_14_2: PASS
- generic_checkpoint_via_universal_adapter: PASS
- context_pack_created: PASS
- legacy_bindings_disabled: PASS
