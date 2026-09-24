-- P18 final hardening: governed erasure metadata mutation and formal gate contract.
CREATE OR REPLACE FUNCTION memory_require_legal_erasure_mutation_context() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF COALESCE(current_setting('app.legal_erasure_mutation_authorized',true),'') <> '1' THEN
    RAISE EXCEPTION 'legal erasure mutation requires governed application boundary' USING ERRCODE='42501';
  END IF;
  RETURN COALESCE(NEW,OLD);
END;
$$;

DO $$
DECLARE t text; DECLARE trg text;
BEGIN
  FOREACH t IN ARRAY ARRAY['legal_erasure_requests','legal_erasure_replay_runs','legal_erasure_gate_p18'] LOOP
    trg:=left('trg_'||t||'_governed',63);
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I',trg,t);
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION memory_require_legal_erasure_mutation_context()',trg,t);
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION legal_erasure_replay_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'legal erasure replay proof is append-only' USING ERRCODE='55000';
END;
$$;
DROP TRIGGER IF EXISTS trg_legal_erasure_replay_append_only ON legal_erasure_replay_runs;
CREATE TRIGGER trg_legal_erasure_replay_append_only BEFORE UPDATE OR DELETE ON legal_erasure_replay_runs
FOR EACH ROW EXECUTE FUNCTION legal_erasure_replay_append_only();

ALTER TABLE legal_erasure_gate_p18 DROP CONSTRAINT IF EXISTS legal_erasure_gate_p18_gate_id_check;
ALTER TABLE legal_erasure_gate_p18 ADD CONSTRAINT legal_erasure_gate_p18_gate_id_check CHECK(gate_id='P18');
ALTER TABLE legal_erasure_gate_p18 DROP CONSTRAINT IF EXISTS legal_erasure_gate_p18_gate_version_check;
ALTER TABLE legal_erasure_gate_p18 ADD CONSTRAINT legal_erasure_gate_p18_gate_version_check CHECK(gate_version='P18-1.0.0');

INSERT INTO schema_meta(key,value) VALUES
('schema_version','memory-0.26.0'),
('p18_gate_contract_version','P18-1.0.0'),
('backup_policy_version','BKP-1.0.0'),
('p18_status','PENDING')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
