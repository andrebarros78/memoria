-- P18 additive correction: repair applied 0035 legal-erasure function and add formal P18 gate.
-- 0035 and 0036 remain immutable.

CREATE OR REPLACE FUNCTION memory_apply_legal_erasure(
  p_item_id text,
  p_erasure_id text,
  p_blinded_fingerprint text,
  p_tombstone_sha text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=public,pg_temp
AS $$
DECLARE v_tenant text;
DECLARE v_tombstone jsonb;
BEGIN
  IF p_blinded_fingerprint !~ '^[0-9a-f]{64}$' OR p_tombstone_sha !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'invalid legal erasure fingerprint' USING ERRCODE='22023';
  END IF;
  SELECT tenant_id INTO v_tenant FROM memory_items WHERE item_id=p_item_id FOR UPDATE;
  IF v_tenant IS NULL THEN RAISE EXCEPTION 'legal erasure target missing' USING ERRCODE='23503'; END IF;
  v_tombstone:=jsonb_build_object('_erasure','FINALIZED','erasure_id',p_erasure_id);

  PERFORM set_config('app.lifecycle_mutation_authorized','1',true);
  PERFORM set_config('app.lifecycle_irreversible_mutation','1',true);
  PERFORM set_config('app.legal_erasure_redaction','1',true);

  UPDATE memory_items SET
    content_json=v_tombstone,
    content_text='[LEGAL_ERASURE_FINALIZED]',
    provenance=jsonb_build_object('legal_erasure','FINALIZED','erasure_id',p_erasure_id),
    confidence=0,source='legal-erasure',source_version='ERM-1.0.0',
    tags=ARRAY['LEGAL_ERASURE_FINALIZED'],content_sha256=p_tombstone_sha,
    validation_status='UNVALIDATED',governor_eligible=false
  WHERE item_id=p_item_id;

  UPDATE memory_versions SET
    content_json=v_tombstone,
    content_text='[LEGAL_ERASURE_FINALIZED]',
    provenance=jsonb_build_object('legal_erasure','FINALIZED','erasure_id',p_erasure_id),
    confidence=0,source='legal-erasure',source_version='ERM-1.0.0',
    tags=ARRAY['LEGAL_ERASURE_FINALIZED'],content_sha256=p_tombstone_sha
  WHERE item_id=p_item_id;

  DELETE FROM memory_embeddings WHERE item_id=p_item_id;

  UPDATE memory_validations SET content_sha256=p_tombstone_sha,status='REJECTED',governor_eligible=false,
    evidence=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id)
  WHERE item_id=p_item_id;
  UPDATE memory_applications SET content_sha256=p_tombstone_sha,
    context=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id)
  WHERE item_id=p_item_id;
  UPDATE memory_outcomes SET expected=jsonb_build_object('legal_erasure',true),actual=jsonb_build_object('legal_erasure',true),
    evidence=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id)
  WHERE item_id=p_item_id;
  UPDATE memory_version_learning SET content_sha256=p_tombstone_sha,learned_confidence=0,evidence_weight=0
  WHERE item_id=p_item_id;
  UPDATE memory_learning_events SET content_sha256=p_tombstone_sha,components=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id)
  WHERE item_id=p_item_id;
  UPDATE memory_artifact_dependencies SET source_content_sha256=p_tombstone_sha WHERE source_item_id=p_item_id;
  UPDATE memory_derived_artifacts a SET status='INVALID',artifact_sha256=NULL,
    metadata=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id),
    invalidation_reason='LEGAL_ERASURE',invalidated_at=now(),updated_at=now()
  WHERE EXISTS(SELECT 1 FROM memory_artifact_dependencies d WHERE d.artifact_id=a.artifact_id AND d.source_item_id=p_item_id);
  UPDATE experience_graph_nodes SET memory_content_sha256=p_tombstone_sha,
    payload=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id),
    provenance=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id)
  WHERE memory_item_id=p_item_id;
  UPDATE memory_causal_assessments SET content_sha256=p_tombstone_sha,
    hypothesis='{"legal_erasure":true}'::jsonb,intervention='{"legal_erasure":true}'::jsonb,
    comparator='{"legal_erasure":true}'::jsonb,confounders='[]'::jsonb,
    confounder_control='{"legal_erasure":true}'::jsonb,mechanism='{"legal_erasure":true}'::jsonb,
    counterfactual='{"legal_erasure":true}'::jsonb,evidence='{"legal_erasure":true}'::jsonb,
    decision_criteria='{"legal_erasure":true}'::jsonb,failure_reasons='[]'::jsonb
  WHERE item_id=p_item_id;
  UPDATE memory_causal_promotions SET content_sha256=p_tombstone_sha,reason='[LEGAL_ERASURE]' WHERE item_id=p_item_id;
  UPDATE sovereign_decision_evidence SET content_sha256=p_tombstone_sha,
    evidence_snapshot=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id)
  WHERE item_id=p_item_id;

  UPDATE lifecycle_recovery_snapshots SET payload_json='{}'::jsonb,
    payload_sha256='44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a',
    status='DESTROYED',destroyed_at=COALESCE(destroyed_at,now())
  WHERE item_id=p_item_id;
  UPDATE lifecycle_requests SET source_content_sha256=p_blinded_fingerprint,
    request_evidence=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id),
    approval_evidence=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id),
    purge_evidence=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id)
  WHERE item_id=p_item_id;
  UPDATE lifecycle_tombstones SET original_content_sha256=p_blinded_fingerprint,
    erasure_fingerprint=p_blinded_fingerprint,
    metadata=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id)
  WHERE item_id=p_item_id;
  UPDATE lifecycle_recovery_proofs SET evidence=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id)
  WHERE request_id IN (SELECT request_id FROM lifecycle_requests WHERE item_id=p_item_id);
  UPDATE lifecycle_events SET payload=jsonb_build_object('legal_erasure',true,'erasure_id',p_erasure_id)
  WHERE item_id=p_item_id OR request_id IN (SELECT request_id FROM lifecycle_requests WHERE item_id=p_item_id);

  UPDATE memory_operator_state SET operator_class=U&'DESCART\00C1VEL',lifecycle_state='PURGED',hold_type=NULL,
    changed_by='LEGAL_ERASURE',changed_at=now() WHERE item_id=p_item_id;
END;
$$;
REVOKE ALL ON FUNCTION memory_apply_legal_erasure(text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_apply_legal_erasure(text,text,text,text) TO memory_app;

CREATE TABLE IF NOT EXISTS legal_erasure_gate_p18(
  tenant_id text NOT NULL,
  gate_id text NOT NULL DEFAULT 'P18',
  gate_version text NOT NULL,
  status text NOT NULL CHECK(status IN ('PENDING','PROVEN')),
  proof_bundle jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(proof_bundle)='object'),
  proven_by text,
  proven_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,gate_id)
);
ALTER TABLE legal_erasure_gate_p18 ENABLE ROW LEVEL SECURITY;
ALTER TABLE legal_erasure_gate_p18 FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON legal_erasure_gate_p18;
CREATE POLICY tenant_isolation ON legal_erasure_gate_p18
  USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));

INSERT INTO schema_meta(key,value) VALUES
('schema_version','memory-0.26.0'),
('p18_gate_version','P18-1.0.0'),
('p18_status','PENDING'),
('plaintext_backup_allowed','false'),
('restore_requires_erasure_replay','true')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
