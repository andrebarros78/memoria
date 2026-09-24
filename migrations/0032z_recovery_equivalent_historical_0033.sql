-- DISASTER RECOVERY 0.26.1: semantic reconstruction of lost historical 0033.
-- Historical attestation only: 0033_lifecycle_manager_m12.sql
-- SHA-256 0e0f50aa9e99642cc12390c5d22e1e819469228bb19d545f6b9a7398b9a39337
-- New filename/checksum prevents false cryptographic continuity.

CREATE TABLE IF NOT EXISTS lifecycle_policies(
  policy_version text PRIMARY KEY,
  status text NOT NULL CHECK(status IN ('ACTIVE','INACTIVE')),
  recovery_window_max_seconds integer NOT NULL CHECK(recovery_window_max_seconds BETWEEN 0 AND 604800),
  created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO lifecycle_policies(policy_version,status,recovery_window_max_seconds)
VALUES('LCP-1.0.0','ACTIVE',604800)
ON CONFLICT(policy_version) DO UPDATE SET status='ACTIVE',recovery_window_max_seconds=EXCLUDED.recovery_window_max_seconds;

CREATE TABLE IF NOT EXISTS lifecycle_requests(
  request_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  policy_version text NOT NULL REFERENCES lifecycle_policies(policy_version) ON DELETE RESTRICT,
  requested_by text NOT NULL,
  reason text NOT NULL,
  status text NOT NULL CHECK(status IN ('REQUESTED','QUARANTINED','APPROVED','PURGED','RECOVERED','FINALIZED','BLOCKED')),
  source_version_no integer NOT NULL,
  source_content_sha256 text NOT NULL,
  recovery_window_seconds integer NOT NULL CHECK(recovery_window_seconds BETWEEN 0 AND 604800),
  request_evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  approval_evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  purge_evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  approved_by text,
  approved_at timestamptz,
  quarantined_at timestamptz,
  purged_at timestamptz,
  recover_until timestamptz,
  recovered_at timestamptz,
  finalized_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lifecycle_requests_item ON lifecycle_requests(tenant_id,item_id,created_at DESC);

CREATE TABLE IF NOT EXISTS lifecycle_recovery_snapshots(
  snapshot_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  request_id text NOT NULL UNIQUE REFERENCES lifecycle_requests(request_id) ON DELETE RESTRICT,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  payload_json jsonb NOT NULL,
  payload_sha256 text NOT NULL CHECK(payload_sha256 ~ '^[0-9a-f]{64}$'),
  status text NOT NULL CHECK(status IN ('ACTIVE','CONSUMED','DESTROYED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  destroyed_at timestamptz
);

CREATE TABLE IF NOT EXISTS lifecycle_tombstones(
  tombstone_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  request_id text NOT NULL UNIQUE REFERENCES lifecycle_requests(request_id) ON DELETE RESTRICT,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  state text NOT NULL CHECK(state IN ('PURGED','RECOVERED','FINALIZED')),
  original_content_sha256 text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lifecycle_recovery_proofs(
  proof_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  request_id text NOT NULL REFERENCES lifecycle_requests(request_id) ON DELETE RESTRICT,
  proof_type text NOT NULL CHECK(proof_type IN ('ROUNDTRIP_RECOVERY','IRREVERSIBILITY')),
  result text NOT NULL CHECK(result IN ('PASS','FAIL')),
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lifecycle_events(
  event_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  request_id text,
  item_id text,
  event_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lifecycle_gate_m12(
  tenant_id text NOT NULL,
  gate_id text NOT NULL DEFAULT 'M12' CHECK(gate_id='M12'),
  gate_version text NOT NULL CHECK(gate_version='M12-1.0.0'),
  status text NOT NULL CHECK(status IN ('PENDING','PROVEN')),
  policy_version text NOT NULL,
  proof_bundle jsonb NOT NULL DEFAULT '{}'::jsonb,
  proven_by text,
  proven_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,gate_id)
);

CREATE OR REPLACE FUNCTION memory_require_lifecycle_mutation_context() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF COALESCE(current_setting('app.lifecycle_mutation_authorized',true),'') <> '1' THEN
    RAISE EXCEPTION 'lifecycle mutation requires governed application boundary' USING ERRCODE='42501';
  END IF;
  RETURN COALESCE(NEW,OLD);
END;
$$;

DO $$
DECLARE t text; DECLARE trg text;
BEGIN
  FOREACH t IN ARRAY ARRAY['lifecycle_requests','lifecycle_recovery_snapshots','lifecycle_tombstones','lifecycle_recovery_proofs','lifecycle_events','lifecycle_gate_m12'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I',t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id))',t);
    trg:=left('trg_'||t||'_governed',63);
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I',trg,t);
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION memory_require_lifecycle_mutation_context()',trg,t);
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION memory_lifecycle_finalize_payload(p_request_id text,p_item_id text,p_final_hash text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
  IF COALESCE(current_setting('app.lifecycle_mutation_authorized',true),'') <> '1' THEN
    RAISE EXCEPTION 'lifecycle finalization requires governed boundary' USING ERRCODE='42501';
  END IF;
  PERFORM set_config('app.lifecycle_irreversible_mutation','1',true);
  UPDATE memory_versions SET content_json=jsonb_build_object('_lifecycle','FINALIZED','request_id',p_request_id),
    content_text='[LIFECYCLE_FINALIZED]',provenance=jsonb_build_object('lifecycle','FINALIZED','request_id',p_request_id),
    confidence=0,source='lifecycle',source_version='LCM-1.0.0',tags=ARRAY['LIFECYCLE_FINALIZED'],content_sha256=p_final_hash
  WHERE item_id=p_item_id;
  UPDATE lifecycle_recovery_snapshots SET payload_json='{}'::jsonb,
    payload_sha256='44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a',status='DESTROYED',destroyed_at=now()
  WHERE request_id=p_request_id;
  UPDATE lifecycle_tombstones SET state='FINALIZED',updated_at=now() WHERE request_id=p_request_id;
  UPDATE lifecycle_requests SET status='FINALIZED',finalized_at=now() WHERE request_id=p_request_id;
END;
$$;
REVOKE ALL ON FUNCTION memory_lifecycle_finalize_payload(text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION memory_lifecycle_finalize_payload(text,text,text) TO memory_app;

INSERT INTO schema_meta(key,value) VALUES
('schema_version','memory-0.25.0'),
('lifecycle_manager_version','LCM-1.0.0'),
('lifecycle_policy_version','LCP-1.0.0'),
('lifecycle_recovery_contract_version','LRC-1.0.0'),
('gate_m12_contract_version','M12-1.0.0'),
('gate_m12_status','PENDING'),
('lifecycle_direct_purge_enabled','false'),
('governed_lifecycle_required','true'),
('lifecycle_historical_0033_sha256','0e0f50aa9e99642cc12390c5d22e1e819469228bb19d545f6b9a7398b9a39337'),
('lifecycle_recovery_lineage','0.26.1-recovery')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();

-- Recovery semantic hardening: historical P17 allowed governed redaction/restoration
-- of version payloads only inside the lifecycle mutation boundary.
CREATE OR REPLACE FUNCTION forbid_append_only_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_TABLE_NAME='memory_versions'
     AND TG_OP='UPDATE'
     AND COALESCE(current_setting('app.lifecycle_irreversible_mutation',true),'')='1' THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'append-only table % forbids %', TG_TABLE_NAME, TG_OP USING ERRCODE='55000';
END;
$$;
