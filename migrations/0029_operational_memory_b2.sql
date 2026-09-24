-- MEMORIA PLUS P14: operational competency memory B2

CREATE TABLE IF NOT EXISTS operational_competencies(
  competency_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  competency_key text NOT NULL,
  title text NOT NULL,
  description text NOT NULL DEFAULT '',
  domain text NOT NULL,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(length(trim(competency_key)) BETWEEN 1 AND 160),
  CHECK(length(trim(title)) BETWEEN 1 AND 300),
  CHECK(length(description) <= 8000),
  CHECK(length(trim(domain)) BETWEEN 1 AND 160),
  CHECK(observed_at >= occurred_at),
  CHECK(valid_to IS NULL OR valid_to > valid_from),
  UNIQUE(tenant_id,competency_key)
);
CREATE INDEX IF NOT EXISTS idx_operational_competencies_bt ON operational_competencies(tenant_id,valid_from,valid_to,observed_at);

CREATE TABLE IF NOT EXISTS operational_skills(
  skill_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  competency_id text NOT NULL REFERENCES operational_competencies(competency_id) ON DELETE RESTRICT,
  skill_key text NOT NULL,
  title text NOT NULL,
  description text NOT NULL DEFAULT '',
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(length(trim(skill_key)) BETWEEN 1 AND 160),
  CHECK(length(trim(title)) BETWEEN 1 AND 300),
  CHECK(length(description) <= 8000),
  CHECK(observed_at >= occurred_at),
  CHECK(valid_to IS NULL OR valid_to > valid_from),
  UNIQUE(tenant_id,competency_id,skill_key)
);
CREATE INDEX IF NOT EXISTS idx_operational_skills_competency ON operational_skills(tenant_id,competency_id,skill_key);
CREATE INDEX IF NOT EXISTS idx_operational_skills_bt ON operational_skills(tenant_id,valid_from,valid_to,observed_at);

CREATE TABLE IF NOT EXISTS operational_skill_versions(
  skill_version_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  skill_id text NOT NULL REFERENCES operational_skills(skill_id) ON DELETE RESTRICT,
  version_label text NOT NULL,
  implementation_version text NOT NULL,
  implementation_sha256 text NOT NULL,
  contract_json jsonb NOT NULL,
  supersedes_skill_version_id text REFERENCES operational_skill_versions(skill_version_id) ON DELETE RESTRICT,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(length(trim(version_label)) BETWEEN 1 AND 120),
  CHECK(length(trim(implementation_version)) BETWEEN 1 AND 120),
  CHECK(implementation_sha256 ~ '^[0-9a-f]{64}$'),
  CHECK(jsonb_typeof(contract_json)='object' AND contract_json <> '{}'::jsonb),
  CHECK(observed_at >= occurred_at),
  CHECK(valid_to IS NULL OR valid_to > valid_from),
  UNIQUE(tenant_id,skill_id,version_label)
);
CREATE INDEX IF NOT EXISTS idx_operational_skill_versions_skill ON operational_skill_versions(tenant_id,skill_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_operational_skill_versions_bt ON operational_skill_versions(tenant_id,valid_from,valid_to,observed_at);

CREATE TABLE IF NOT EXISTS operational_capabilities(
  capability_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  skill_version_id text NOT NULL REFERENCES operational_skill_versions(skill_version_id) ON DELETE RESTRICT,
  capability_key text NOT NULL,
  contract_json jsonb NOT NULL,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(length(trim(capability_key)) BETWEEN 1 AND 160),
  CHECK(jsonb_typeof(contract_json)='object' AND contract_json <> '{}'::jsonb),
  CHECK(observed_at >= occurred_at),
  CHECK(valid_to IS NULL OR valid_to > valid_from),
  UNIQUE(tenant_id,skill_version_id,capability_key)
);
CREATE INDEX IF NOT EXISTS idx_operational_capabilities_version ON operational_capabilities(tenant_id,skill_version_id,capability_key);
CREATE INDEX IF NOT EXISTS idx_operational_capabilities_bt ON operational_capabilities(tenant_id,valid_from,valid_to,observed_at);

CREATE TABLE IF NOT EXISTS operational_proofs(
  proof_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  skill_version_id text NOT NULL REFERENCES operational_skill_versions(skill_version_id) ON DELETE RESTRICT,
  proof_type text NOT NULL CHECK(proof_type IN ('REPLAY','RECOVERY')),
  result text NOT NULL CHECK(result IN ('PASS','FAIL')),
  artifact_ref text NOT NULL,
  artifact_sha256 text NOT NULL,
  evidence jsonb NOT NULL,
  executed_at timestamptz NOT NULL,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(length(trim(artifact_ref)) BETWEEN 1 AND 500),
  CHECK(artifact_sha256 ~ '^[0-9a-f]{64}$'),
  CHECK(jsonb_typeof(evidence)='object' AND evidence <> '{}'::jsonb),
  CHECK(observed_at >= occurred_at),
  CHECK(valid_to IS NULL OR valid_to > valid_from)
);
CREATE INDEX IF NOT EXISTS idx_operational_proofs_version ON operational_proofs(tenant_id,skill_version_id,proof_type,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_operational_proofs_bt ON operational_proofs(tenant_id,valid_from,valid_to,observed_at);

CREATE TABLE IF NOT EXISTS operational_status_events(
  status_event_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  skill_version_id text NOT NULL REFERENCES operational_skill_versions(skill_version_id) ON DELETE RESTRICT,
  status text NOT NULL CHECK(status IN ('PROVEN','STALE','FAILED','DEPRECATED')),
  reason text NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  trigger_proof_id text REFERENCES operational_proofs(proof_id) ON DELETE RESTRICT,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(length(trim(reason)) BETWEEN 1 AND 4000),
  CHECK(jsonb_typeof(evidence)='object'),
  CHECK(observed_at >= occurred_at),
  CHECK(valid_to IS NULL OR valid_to > valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_operational_status_trigger_proof ON operational_status_events(trigger_proof_id) WHERE trigger_proof_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_operational_status_version ON operational_status_events(tenant_id,skill_version_id,created_at DESC,status_event_id DESC);
CREATE INDEX IF NOT EXISTS idx_operational_status_bt ON operational_status_events(tenant_id,valid_from,valid_to,observed_at);

CREATE OR REPLACE FUNCTION memory_require_operational_mutation_context() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF COALESCE(current_setting('app.operational_mutation_authorized',true),'0') <> '1' THEN
    RAISE EXCEPTION 'operational memory mutation requires canonical API/store boundary' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION memory_validate_operational_skill() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE p_tenant text;
BEGIN
  SELECT tenant_id INTO p_tenant FROM operational_competencies WHERE competency_id=NEW.competency_id;
  IF p_tenant IS NULL THEN RAISE EXCEPTION 'operational competency not found' USING ERRCODE='23503'; END IF;
  IF p_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'cross-tenant operational skill forbidden' USING ERRCODE='42501'; END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION memory_validate_operational_skill_version() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE s_tenant text;
DECLARE old_skill text;
DECLARE old_tenant text;
BEGIN
  SELECT tenant_id INTO s_tenant FROM operational_skills WHERE skill_id=NEW.skill_id;
  IF s_tenant IS NULL THEN RAISE EXCEPTION 'operational skill not found' USING ERRCODE='23503'; END IF;
  IF s_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'cross-tenant operational skill version forbidden' USING ERRCODE='42501'; END IF;
  IF NEW.supersedes_skill_version_id IS NOT NULL THEN
    SELECT skill_id,tenant_id INTO old_skill,old_tenant FROM operational_skill_versions WHERE skill_version_id=NEW.supersedes_skill_version_id;
    IF old_skill IS NULL THEN RAISE EXCEPTION 'superseded operational skill version not found' USING ERRCODE='23503'; END IF;
    IF old_tenant<>NEW.tenant_id OR old_skill<>NEW.skill_id THEN RAISE EXCEPTION 'operational skill version may supersede only same skill and tenant' USING ERRCODE='23514'; END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION memory_validate_operational_capability() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_tenant text;
DECLARE latest_status text;
BEGIN
  SELECT tenant_id INTO v_tenant FROM operational_skill_versions WHERE skill_version_id=NEW.skill_version_id;
  IF v_tenant IS NULL THEN RAISE EXCEPTION 'operational skill version not found' USING ERRCODE='23503'; END IF;
  IF v_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'cross-tenant operational capability forbidden' USING ERRCODE='42501'; END IF;
  SELECT status INTO latest_status FROM operational_status_events WHERE skill_version_id=NEW.skill_version_id ORDER BY created_at DESC,status_event_id DESC LIMIT 1;
  IF latest_status='DEPRECATED' THEN RAISE EXCEPTION 'cannot add capability to deprecated skill version' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION memory_validate_operational_proof() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_tenant text;
DECLARE latest_status text;
BEGIN
  SELECT tenant_id INTO v_tenant FROM operational_skill_versions WHERE skill_version_id=NEW.skill_version_id;
  IF v_tenant IS NULL THEN RAISE EXCEPTION 'operational skill version not found' USING ERRCODE='23503'; END IF;
  IF v_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'cross-tenant operational proof forbidden' USING ERRCODE='42501'; END IF;
  SELECT status INTO latest_status FROM operational_status_events WHERE skill_version_id=NEW.skill_version_id ORDER BY created_at DESC,status_event_id DESC LIMIT 1;
  IF latest_status='DEPRECATED' THEN RAISE EXCEPTION 'deprecated skill version cannot receive new proof' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION memory_validate_operational_status_event() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v_tenant text;
DECLARE previous_status text;
DECLARE replay_ok boolean;
DECLARE recovery_ok boolean;
DECLARE gate_at timestamptz;
BEGIN
  SELECT tenant_id INTO v_tenant FROM operational_skill_versions WHERE skill_version_id=NEW.skill_version_id;
  IF v_tenant IS NULL THEN RAISE EXCEPTION 'operational skill version not found' USING ERRCODE='23503'; END IF;
  IF v_tenant<>NEW.tenant_id THEN RAISE EXCEPTION 'cross-tenant operational status forbidden' USING ERRCODE='42501'; END IF;
  SELECT status INTO previous_status FROM operational_status_events WHERE skill_version_id=NEW.skill_version_id ORDER BY created_at DESC,status_event_id DESC LIMIT 1;
  IF previous_status='DEPRECATED' THEN RAISE EXCEPTION 'DEPRECATED operational status is terminal' USING ERRCODE='23514'; END IF;
  IF NEW.status='STALE' AND previous_status IS DISTINCT FROM 'PROVEN' THEN
    RAISE EXCEPTION 'STALE requires prior PROVEN status' USING ERRCODE='23514';
  END IF;
  IF NEW.status='PROVEN' THEN
    SELECT created_at INTO gate_at FROM operational_status_events WHERE skill_version_id=NEW.skill_version_id AND status IN ('STALE','FAILED') ORDER BY created_at DESC,status_event_id DESC LIMIT 1;
    SELECT COALESCE((SELECT result='PASS' FROM operational_proofs WHERE skill_version_id=NEW.skill_version_id AND proof_type='REPLAY' AND (gate_at IS NULL OR created_at > gate_at) ORDER BY created_at DESC,proof_id DESC LIMIT 1),false) INTO replay_ok;
    SELECT COALESCE((SELECT result='PASS' FROM operational_proofs WHERE skill_version_id=NEW.skill_version_id AND proof_type='RECOVERY' AND (gate_at IS NULL OR created_at > gate_at) ORDER BY created_at DESC,proof_id DESC LIMIT 1),false) INTO recovery_ok;
    IF NOT replay_ok OR NOT recovery_ok THEN
      RAISE EXCEPTION 'PROVEN requires REPLAY PASS and RECOVERY PASS proofs' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.trigger_proof_id IS NOT NULL AND NOT EXISTS(
    SELECT 1 FROM operational_proofs p WHERE p.proof_id=NEW.trigger_proof_id AND p.skill_version_id=NEW.skill_version_id AND p.tenant_id=NEW.tenant_id
  ) THEN
    RAISE EXCEPTION 'operational status trigger proof mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;

-- Canonical mutation boundary, tenant setting, bitemporal normalization and append-only protection.
DO $$
DECLARE r record;
DECLARE trg text;
BEGIN
  FOR r IN SELECT unnest(ARRAY[
    'operational_competencies','operational_skills','operational_skill_versions','operational_capabilities','operational_proofs','operational_status_events'
  ]) AS table_name LOOP
    trg:=left('trg_'||r.table_name||'_set_tenant',63);
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I',trg,r.table_name);
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_context()',trg,r.table_name);
    trg:=left('trg_'||r.table_name||'_context',63);
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I',trg,r.table_name);
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION memory_require_operational_mutation_context()',trg,r.table_name);
    trg:=left('trg_'||r.table_name||'_bitemporal_insert',63);
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I',trg,r.table_name);
    EXECUTE format('CREATE TRIGGER %I BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION normalize_bitemporal_insert()',trg,r.table_name);
    trg:=left('trg_'||r.table_name||'_append_only',63);
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I',trg,r.table_name);
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation()',trg,r.table_name);
  END LOOP;
END $$;

DROP TRIGGER IF EXISTS trg_operational_skills_validate ON operational_skills;
CREATE TRIGGER trg_operational_skills_validate BEFORE INSERT ON operational_skills FOR EACH ROW EXECUTE FUNCTION memory_validate_operational_skill();
DROP TRIGGER IF EXISTS trg_operational_skill_versions_validate ON operational_skill_versions;
CREATE TRIGGER trg_operational_skill_versions_validate BEFORE INSERT ON operational_skill_versions FOR EACH ROW EXECUTE FUNCTION memory_validate_operational_skill_version();
DROP TRIGGER IF EXISTS trg_operational_capabilities_validate ON operational_capabilities;
CREATE TRIGGER trg_operational_capabilities_validate BEFORE INSERT ON operational_capabilities FOR EACH ROW EXECUTE FUNCTION memory_validate_operational_capability();
DROP TRIGGER IF EXISTS trg_operational_proofs_validate ON operational_proofs;
CREATE TRIGGER trg_operational_proofs_validate BEFORE INSERT ON operational_proofs FOR EACH ROW EXECUTE FUNCTION memory_validate_operational_proof();
DROP TRIGGER IF EXISTS trg_operational_status_events_validate ON operational_status_events;
CREATE TRIGGER trg_operational_status_events_validate BEFORE INSERT ON operational_status_events FOR EACH ROW EXECUTE FUNCTION memory_validate_operational_status_event();

DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT unnest(ARRAY[
    'operational_competencies','operational_skills','operational_skill_versions','operational_capabilities','operational_proofs','operational_status_events'
  ]) AS table_name LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',r.table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',r.table_name);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I',r.table_name);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id))',r.table_name);
  END LOOP;
END $$;

CREATE OR REPLACE VIEW operational_skill_catalog AS
SELECT
  c.tenant_id,c.competency_id,c.competency_key,c.title AS competency_title,c.domain,
  s.skill_id,s.skill_key,s.title AS skill_title,
  v.skill_version_id,v.version_label,v.implementation_version,v.implementation_sha256,v.contract_json,v.supersedes_skill_version_id,
  COALESCE(ls.status,'UNPROVEN') AS current_status,
  ls.reason AS status_reason,
  ls.status_event_id,
  ls.created_at AS status_recorded_at,
  COALESCE((SELECT p.result='PASS' FROM operational_proofs p WHERE p.skill_version_id=v.skill_version_id AND p.proof_type='REPLAY' ORDER BY p.created_at DESC,p.proof_id DESC LIMIT 1),false) AS replay_proven,
  COALESCE((SELECT p.result='PASS' FROM operational_proofs p WHERE p.skill_version_id=v.skill_version_id AND p.proof_type='RECOVERY' ORDER BY p.created_at DESC,p.proof_id DESC LIMIT 1),false) AS recovery_proven,
  (SELECT count(*) FROM operational_capabilities cp WHERE cp.skill_version_id=v.skill_version_id) AS capability_count,
  v.created_at AS version_created_at
FROM operational_competencies c
JOIN operational_skills s ON s.competency_id=c.competency_id
JOIN operational_skill_versions v ON v.skill_id=s.skill_id
LEFT JOIN LATERAL (
  SELECT e.status,e.reason,e.status_event_id,e.created_at
  FROM operational_status_events e
  WHERE e.skill_version_id=v.skill_version_id
  ORDER BY e.created_at DESC,e.status_event_id DESC LIMIT 1
) ls ON true;

ALTER TABLE temporal_entity_contracts DISABLE TRIGGER trg_temporal_contract_immutable;
INSERT INTO temporal_entity_contracts(entity_name,temporal_kind,rationale,storage_mode,storage_entity) VALUES
('operational_competencies','BITEMPORAL','formal operational competency assertion','INLINE',NULL),
('operational_skills','BITEMPORAL','formal skill assertion within competency','INLINE',NULL),
('operational_skill_versions','BITEMPORAL','versioned operational skill contract','INLINE',NULL),
('operational_capabilities','BITEMPORAL','capability assertion bound to exact skill version','INLINE',NULL),
('operational_proofs','BITEMPORAL','replay/recovery proof event','INLINE',NULL),
('operational_status_events','BITEMPORAL','append-only skill-version operational status event','INLINE',NULL)
ON CONFLICT(entity_name) DO NOTHING;
ALTER TABLE temporal_entity_contracts ENABLE TRIGGER trg_temporal_contract_immutable;

GRANT SELECT,INSERT ON operational_competencies TO memory_app;
GRANT SELECT,INSERT ON operational_skills TO memory_app;
GRANT SELECT,INSERT ON operational_skill_versions TO memory_app;
GRANT SELECT,INSERT ON operational_capabilities TO memory_app;
GRANT SELECT,INSERT ON operational_proofs TO memory_app;
GRANT SELECT,INSERT ON operational_status_events TO memory_app;
GRANT SELECT ON operational_skill_catalog TO memory_app;

INSERT INTO schema_meta(key,value) VALUES
('operational_memory_version','OM-1.0.0'),
('operational_memory_statuses','PROVEN,STALE,FAILED,DEPRECATED'),
('operational_memory_required_proofs','REPLAY,RECOVERY'),
('bitemporal_contract_entities',(SELECT count(*)::text FROM temporal_entity_contracts)),
('bitemporal_fact_entities',(SELECT count(*)::text FROM temporal_entity_contracts WHERE temporal_kind='BITEMPORAL')),
('schema_version','memory-0.22.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
