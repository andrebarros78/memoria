-- V5.2 runtime least-privilege hardening.
-- Historical migrations remain immutable. This migration removes the broad
-- table grants introduced by 0011 and re-grants only capabilities exercised by
-- the authenticated runtime. Schema migrations remain an administrative-plane
-- responsibility and are read-only to memory_app.

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM memory_app;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM memory_app;

ALTER DEFAULT PRIVILEGES FOR ROLE memory_admin IN SCHEMA public
  REVOKE ALL PRIVILEGES ON TABLES FROM memory_app;
ALTER DEFAULT PRIVILEGES FOR ROLE memory_admin IN SCHEMA public
  REVOKE ALL PRIVILEGES ON SEQUENCES FROM memory_app;

GRANT USAGE ON SCHEMA public TO memory_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO memory_app;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'agent_leases','audit_events','checkpoints','context_packs',
    'conversation_ingestion_event_temporal','conversation_ingestion_events',
    'economic_attributions','economic_entities','economic_results','economic_states',
    'experience_graph_edges','experience_graph_nodes','experience_graph_relation_rules',
    'external_session_bindings','idempotency_records','legal_erasure_gate_p18',
    'legal_erasure_replay_runs','legal_erasure_requests','learning_policy_versions',
    'lifecycle_gate_m12','lifecycle_policies','lifecycle_recovery_proofs',
    'lifecycle_recovery_snapshots','lifecycle_requests','memory_applications',
    'memory_artifact_dependencies','memory_capacity_snapshots','memory_causal_assessments',
    'memory_causal_promotions','memory_derived_artifacts','memory_embeddings',
    'memory_evolution_proofs','memory_experience_edges','memory_items',
    'memory_knowledge_relations','memory_operator_state','memory_version_learning',
    'memory_versions','ontology_relation_rules','ontology_transition_rules',
    'operational_capabilities','operational_competencies','operational_proofs',
    'operational_skill_catalog','operational_skill_versions','operational_skills',
    'operational_status_events','retention_holds','retrieval_quality_golden_sets',
    'retrieval_quality_runs','retrieval_traces','schema_meta','schema_migrations',
    'session_checkpoints','session_rotations','sovereign_decision_evidence',
    'sovereign_decision_outcomes','sovereign_decision_replays','sovereign_decisions',
    'sovereign_sessions','temporal_entity_contracts'
  ] LOOP
    EXECUTE format('GRANT SELECT ON TABLE %I TO memory_app', t);
  END LOOP;

  FOREACH t IN ARRAY ARRAY[
    'agent_leases','audit_events','checkpoints','context_packs',
    'conversation_ingestion_event_temporal','conversation_ingestion_events',
    'economic_attributions','economic_entities','economic_results','economic_states',
    'experience_graph_edges','experience_graph_nodes','external_session_bindings',
    'idempotency_records','legal_erasure_gate_p18','legal_erasure_replay_runs',
    'legal_erasure_requests','lifecycle_events','lifecycle_gate_m12',
    'lifecycle_recovery_proofs','lifecycle_recovery_snapshots','lifecycle_requests',
    'lifecycle_tombstones','memory_applications','memory_artifact_dependencies',
    'memory_capacity_snapshots','memory_causal_assessments','memory_derived_artifacts',
    'memory_embeddings','memory_events','memory_evolution_proofs','memory_experience_edges',
    'memory_items','memory_knowledge_relations','memory_learning_events',
    'memory_operator_state','memory_outcomes','memory_validations','memory_version_learning',
    'memory_versions','operational_capabilities','operational_competencies',
    'operational_proofs','operational_skill_versions','operational_skills',
    'operational_status_events','retention_holds','retrieval_quality_golden_sets',
    'retrieval_quality_runs','retrieval_traces','session_checkpoints','session_rotations',
    'sovereign_decision_evidence','sovereign_decision_outcomes',
    'sovereign_decision_replays','sovereign_decisions','sovereign_sessions'
  ] LOOP
    EXECUTE format('GRANT INSERT ON TABLE %I TO memory_app', t);
  END LOOP;

  FOREACH t IN ARRAY ARRAY[
    'agent_leases','conversation_ingestion_events','external_session_bindings',
    'legal_erasure_requests','lifecycle_recovery_snapshots','lifecycle_requests',
    'lifecycle_tombstones','memory_embeddings','memory_items','memory_operator_state',
    'memory_version_learning','memory_versions','retention_holds','session_rotations',
    'sovereign_sessions'
  ] LOOP
    EXECUTE format('GRANT UPDATE ON TABLE %I TO memory_app', t);
  END LOOP;
END $$;

GRANT DELETE ON TABLE memory_embeddings TO memory_app;

-- Runtime may read migration state but may never mutate it directly.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE schema_migrations FROM memory_app;

-- Audit chain is append-only to the runtime role.
REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE audit_events FROM memory_app;
GRANT SELECT, INSERT ON TABLE audit_events TO memory_app;

-- Deprecated/internal audit and provider tables are not part of the V5.2 runtime API.
REVOKE ALL PRIVILEGES ON TABLE legacy_security_audit, provider_invocations FROM memory_app;

-- Global schema metadata can be read by runtime, but only three runtime gate keys
-- may be mutated through this constrained security-definer function.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE schema_meta FROM memory_app;
GRANT SELECT ON TABLE schema_meta TO memory_app;

CREATE OR REPLACE FUNCTION memory_set_runtime_gate(p_key text, p_value text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp
AS $$
BEGIN
  IF p_key NOT IN ('restore_erasure_replay_status','p18_status','gate_m12_status') THEN
    RAISE EXCEPTION 'runtime schema_meta key is not authorized: %', p_key USING ERRCODE='42501';
  END IF;
  IF p_value NOT IN ('PASS','PROVEN') THEN
    RAISE EXCEPTION 'runtime schema_meta value is not authorized: %', p_value USING ERRCODE='22023';
  END IF;
  INSERT INTO public.schema_meta(key,value) VALUES(p_key,p_value)
  ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
END;
$$;
REVOKE ALL ON FUNCTION memory_set_runtime_gate(text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_set_runtime_gate(text,text) TO memory_app;

INSERT INTO schema_meta(key,value) VALUES('runtime_least_privilege_version','RLP-1.0.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
