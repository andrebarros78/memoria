-- MEMORIA PLUS P18: legal erasure across backups/manifests and governed restore.
-- The external erasure ledger is deliberately outside PostgreSQL backups.

CREATE TABLE IF NOT EXISTS legal_erasure_requests(
  erasure_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  lifecycle_request_id text NOT NULL UNIQUE REFERENCES lifecycle_requests(request_id) ON DELETE RESTRICT,
  item_id text,
  target_token text NOT NULL CHECK(target_token ~ '^[0-9a-f]{64}$'),
  reason_code text NOT NULL CHECK(length(btrim(reason_code))>0),
  status text NOT NULL CHECK(status IN ('RECORDED','APPLIED','BACKUP_SHRED_PENDING','COMPLETE')),
  external_ledger_seq bigint NOT NULL CHECK(external_ledger_seq>0),
  external_ledger_hmac text NOT NULL CHECK(external_ledger_hmac ~ '^[0-9a-f]{64}$'),
  blinded_content_fingerprint text NOT NULL CHECK(blinded_content_fingerprint ~ '^[0-9a-f]{64}$'),
  backup_cutoff_at timestamptz NOT NULL,
  backup_shred_evidence jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(backup_shred_evidence)='object'),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_legal_erasure_target ON legal_erasure_requests(tenant_id,target_token,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_legal_erasure_status ON legal_erasure_requests(tenant_id,status,created_at DESC);

CREATE TABLE IF NOT EXISTS legal_erasure_replay_runs(
  replay_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  source_ref text NOT NULL,
  ledger_entries bigint NOT NULL CHECK(ledger_entries>=0),
  matched_targets bigint NOT NULL CHECK(matched_targets>=0),
  redacted_targets bigint NOT NULL CHECK(redacted_targets>=0),
  result text NOT NULL CHECK(result IN ('PASS','FAIL')),
  evidence jsonb NOT NULL CHECK(jsonb_typeof(evidence)='object'),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_legal_erasure_replays ON legal_erasure_replay_runs(tenant_id,created_at DESC);

ALTER TABLE lifecycle_tombstones ADD COLUMN IF NOT EXISTS erasure_fingerprint text;
ALTER TABLE lifecycle_tombstones DROP CONSTRAINT IF EXISTS lifecycle_tombstones_erasure_fingerprint_check;
ALTER TABLE lifecycle_tombstones ADD CONSTRAINT lifecycle_tombstones_erasure_fingerprint_check
  CHECK(erasure_fingerprint IS NULL OR erasure_fingerprint ~ '^[0-9a-f]{64}$');

CREATE OR REPLACE FUNCTION forbid_append_only_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME='memory_versions'
     AND TG_OP='UPDATE'
     AND COALESCE(current_setting('app.lifecycle_irreversible_mutation',true),'')='1' THEN
    RETURN NEW;
  END IF;
  IF TG_OP='UPDATE'
     AND COALESCE(current_setting('app.legal_erasure_redaction',true),'')='1'
     AND TG_TABLE_NAME = ANY(ARRAY[
       'memory_validations','memory_applications','memory_outcomes','memory_experience_edges',
       'memory_learning_events','experience_graph_nodes','experience_graph_edges',
       'memory_causal_assessments','memory_causal_promotions','sovereign_decision_evidence',
       'lifecycle_recovery_proofs','lifecycle_events'
     ]) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'append-only table % forbids %', TG_TABLE_NAME, TG_OP USING ERRCODE='55000';
END;
$$;

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

  UPDATE memory_operator_state SET operator_class='DESCARTÁVEL',lifecycle_state='PURGED',hold_type=NULL,
    changed_by='LEGAL_ERASURE',changed_at=now() WHERE item_id=p_item_id;
END;
$$;
REVOKE ALL ON FUNCTION memory_apply_legal_erasure(text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_apply_legal_erasure(text,text,text,text) TO memory_app;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['legal_erasure_requests','legal_erasure_replay_runs'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I',t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id))',t);
  END LOOP;
END $$;

INSERT INTO schema_meta(key,value) VALUES
('schema_version','memory-0.26.0'),
('legal_erasure_manager_version','ERM-1.0.0'),
('erasure_policy_version','ERP-1.0.0'),
('external_erasure_ledger_version','EL-1.0.0'),
('backup_crypto_version','BCP-1.0.0'),
('restore_erasure_contract_version','REC-1.0.0'),
('restore_requires_erasure_replay','true'),
('plaintext_backup_allowed','false'),
('p18_status','PENDING')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
