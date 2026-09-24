-- P18 hardening: cover canonical events, request hashes, relations, traces and governed audit rewrite.

CREATE OR REPLACE FUNCTION forbid_append_only_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME='memory_versions' AND TG_OP='UPDATE'
     AND COALESCE(current_setting('app.lifecycle_irreversible_mutation',true),'')='1' THEN RETURN NEW; END IF;
  IF TG_OP='UPDATE' AND COALESCE(current_setting('app.legal_erasure_redaction',true),'')='1'
     AND TG_TABLE_NAME = ANY(ARRAY[
       'memory_validations','memory_applications','memory_outcomes','memory_experience_edges',
       'memory_learning_events','experience_graph_nodes','experience_graph_edges',
       'memory_causal_assessments','memory_causal_promotions','sovereign_decision_evidence',
       'lifecycle_recovery_proofs','lifecycle_events','memory_events','memory_knowledge_relations',
       'memory_ontology_transitions'
     ]) THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME='audit_events' AND TG_OP='UPDATE'
     AND COALESCE(current_setting('app.legal_erasure_audit_rewrite',true),'')='1' THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'append-only table % forbids %', TG_TABLE_NAME, TG_OP USING ERRCODE='55000';
END;
$$;

CREATE OR REPLACE FUNCTION memory_apply_legal_erasure_extended(
  p_item_id text,p_erasure_id text,p_blinded_fingerprint text,p_tombstone_sha text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
  PERFORM memory_apply_legal_erasure(p_item_id,p_erasure_id,p_blinded_fingerprint,p_tombstone_sha);
  PERFORM set_config('app.lifecycle_irreversible_mutation','1',true);
  PERFORM set_config('app.legal_erasure_redaction','1',true);

  UPDATE memory_items SET memory_key='LEGAL_ERASURE:'||substr(p_blinded_fingerprint,1,16) WHERE item_id=p_item_id;
  UPDATE memory_versions SET request_sha256=p_blinded_fingerprint WHERE item_id=p_item_id;
  UPDATE memory_events SET payload=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id),
    request_sha256=p_blinded_fingerprint WHERE item_id=p_item_id;
  UPDATE memory_knowledge_relations SET provenance=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id),
    confidence=0,created_by='LEGAL_ERASURE',stale_reason='LEGAL_ERASURE'
    WHERE from_item_id=p_item_id OR to_item_id=p_item_id;
  UPDATE memory_ontology_transitions SET actor_id='LEGAL_ERASURE',reason='[LEGAL_ERASURE]',
    evidence=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id) WHERE item_id=p_item_id;
  UPDATE retention_holds SET reason='[LEGAL_ERASURE]',created_by='LEGAL_ERASURE' WHERE item_id=p_item_id;
  UPDATE memory_experience_edges SET evidence=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id)
    WHERE from_id=p_item_id OR to_id=p_item_id OR evidence::text LIKE '%'||p_item_id||'%';
  UPDATE experience_graph_nodes SET entity_ref='LEGAL_ERASURE:'||node_id,created_by='LEGAL_ERASURE'
    WHERE memory_item_id=p_item_id;
  UPDATE retrieval_traces SET query_text='[LEGAL_ERASURE]',candidates='[]'::jsonb,selected='[]'::jsonb,
    conflicts='[]'::jsonb,state_json='{}'::jsonb
    WHERE candidates::text LIKE '%'||p_item_id||'%' OR selected::text LIKE '%'||p_item_id||'%'
       OR conflicts::text LIKE '%'||p_item_id||'%' OR state_json::text LIKE '%'||p_item_id||'%';
  DELETE FROM idempotency_records
    WHERE response_json::text LIKE '%'||p_item_id||'%' OR operation='revise:'||p_item_id;
END;
$$;
REVOKE ALL ON FUNCTION memory_apply_legal_erasure_extended(text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_apply_legal_erasure_extended(text,text,text,text) TO memory_app;

INSERT INTO schema_meta(key,value) VALUES
('legal_erasure_redaction_version','ERD-1.1.0'),
('audit_legal_erasure_rewrite','GOVERNED_RECHAIN_V1')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();