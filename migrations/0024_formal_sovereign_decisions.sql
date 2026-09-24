-- P10 formal sovereign decision memory.

CREATE TABLE sovereign_decisions(
  decision_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  mission_id text NOT NULL,
  mission_anchor_type text NOT NULL CHECK(mission_anchor_type IN ('SESSION','CHECKPOINT')),
  mission_anchor_id text NOT NULL,
  mission_snapshot jsonb NOT NULL CHECK(jsonb_typeof(mission_snapshot)='object'),
  criticality text NOT NULL CHECK(criticality IN ('NORMAL','HIGH','CRITICAL')),
  objective text NOT NULL CHECK(length(btrim(objective))>0),
  decision_context jsonb NOT NULL CHECK(jsonb_typeof(decision_context)='object'),
  alternatives jsonb NOT NULL CHECK(jsonb_typeof(alternatives)='array' AND jsonb_array_length(alternatives)>=1),
  rationale text NOT NULL CHECK(length(btrim(rationale))>0),
  authority jsonb NOT NULL CHECK(jsonb_typeof(authority)='object' AND authority <> '{}'::jsonb),
  action jsonb NOT NULL CHECK(jsonb_typeof(action)='object' AND action <> '{}'::jsonb),
  expected_outcome jsonb NOT NULL CHECK(jsonb_typeof(expected_outcome)='object' AND expected_outcome <> '{}'::jsonb),
  decision_proof jsonb NOT NULL CHECK(jsonb_typeof(decision_proof)='object' AND decision_proof <> '{}'::jsonb),
  core_sha256 text NOT NULL CHECK(core_sha256 ~ '^[0-9a-f]{64}$'),
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sovereign_decisions_mission_idx ON sovereign_decisions(tenant_id,mission_id,occurred_at,decision_id);

CREATE TABLE sovereign_decision_evidence(
  decision_evidence_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  decision_id text NOT NULL REFERENCES sovereign_decisions(decision_id),
  role text NOT NULL CHECK(length(btrim(role))>0),
  item_id text NOT NULL REFERENCES memory_items(item_id),
  version_id text NOT NULL REFERENCES memory_versions(version_id),
  version_no integer NOT NULL CHECK(version_no>=1),
  content_sha256 text NOT NULL CHECK(content_sha256 ~ '^[0-9a-f]{64}$'),
  category_snapshot text NOT NULL,
  evidence_snapshot jsonb NOT NULL CHECK(jsonb_typeof(evidence_snapshot)='object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(decision_id,role,item_id,version_id)
);
CREATE INDEX sovereign_decision_evidence_decision_idx ON sovereign_decision_evidence(tenant_id,decision_id,role,item_id);

CREATE TABLE sovereign_decision_outcomes(
  decision_outcome_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  decision_id text NOT NULL REFERENCES sovereign_decisions(decision_id),
  success boolean NOT NULL,
  actual_outcome jsonb NOT NULL CHECK(jsonb_typeof(actual_outcome)='object' AND actual_outcome <> '{}'::jsonb),
  proof jsonb NOT NULL CHECK(jsonb_typeof(proof)='object' AND proof <> '{}'::jsonb),
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  recorded_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sovereign_decision_outcomes_decision_idx ON sovereign_decision_outcomes(tenant_id,decision_id,occurred_at,decision_outcome_id);

CREATE TABLE sovereign_decision_replays(
  replay_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  decision_id text NOT NULL REFERENCES sovereign_decisions(decision_id),
  replay_sha256 text NOT NULL CHECK(replay_sha256 ~ '^[0-9a-f]{64}$'),
  replay_package jsonb NOT NULL CHECK(jsonb_typeof(replay_package)='object' AND replay_package <> '{}'::jsonb),
  requested_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sovereign_decision_replays_decision_idx ON sovereign_decision_replays(tenant_id,decision_id,created_at,replay_id);

CREATE TABLE sovereign_decision_legacy_inventory(
  inventory_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  application_id text NOT NULL,
  legacy_decision_id text NOT NULL,
  legacy_mission_id text,
  classification text NOT NULL DEFAULT 'PRE_P10_TEXTUAL_REFERENCE',
  inventoried_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(application_id)
);

INSERT INTO sovereign_decision_legacy_inventory(inventory_id,tenant_id,application_id,legacy_decision_id,legacy_mission_id)
SELECT 'dli-'||md5(application_id),tenant_id,application_id,decision_id,mission_id
FROM memory_applications
WHERE decision_id IS NOT NULL
ON CONFLICT(application_id) DO NOTHING;

CREATE OR REPLACE FUNCTION memory_resolve_decision_mission_anchor() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE s sovereign_sessions%ROWTYPE; DECLARE cp checkpoints%ROWTYPE;
BEGIN
  SELECT * INTO s FROM sovereign_sessions WHERE session_id=NEW.mission_id;
  IF s.session_id IS NOT NULL THEN
    NEW.tenant_id := s.tenant_id;
    NEW.mission_anchor_type := 'SESSION';
    NEW.mission_anchor_id := s.session_id;
    NEW.mission_snapshot := jsonb_build_object(
      'session_id',s.session_id,'identity',s.identity_json,'scope',s.scope,'objective',s.objective,
      'critical_rules',s.critical_rules,'operational_state',s.operational_state,
      'last_confirmed_action',s.last_confirmed_action,'blockers',s.blockers,'pending',s.pending,
      'next_safe_action',s.next_safe_action,'active_authorizations',s.active_authorizations,
      'required_memory_ids',to_jsonb(s.required_memory_ids),'updated_at',s.updated_at
    );
    RETURN NEW;
  END IF;
  SELECT * INTO cp FROM checkpoints WHERE mission_id=NEW.mission_id ORDER BY step_index DESC,created_at DESC LIMIT 1;
  IF cp.checkpoint_id IS NOT NULL THEN
    NEW.tenant_id := cp.tenant_id;
    NEW.mission_anchor_type := 'CHECKPOINT';
    NEW.mission_anchor_id := cp.checkpoint_id;
    NEW.mission_snapshot := jsonb_build_object(
      'checkpoint_id',cp.checkpoint_id,'namespace',cp.namespace,'mission_id',cp.mission_id,
      'step_index',cp.step_index,'state',cp.state_json,'state_sha256',cp.state_sha256,
      'project_id',cp.project_id,'created_at',cp.created_at
    );
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'formal decision requires an existing sovereign session or checkpoint mission anchor' USING ERRCODE='23503';
END;
$$;

CREATE OR REPLACE FUNCTION memory_validate_decision_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE d_tenant text; DECLARE m_tenant text; DECLARE m_category text; DECLARE v record;
BEGIN
  SELECT tenant_id INTO d_tenant FROM sovereign_decisions WHERE decision_id=NEW.decision_id;
  SELECT tenant_id,category INTO m_tenant,m_category FROM memory_items WHERE item_id=NEW.item_id;
  SELECT version_id,version_no,content_sha256,content_json,content_text,provenance,source,source_version,tags
    INTO v FROM memory_versions WHERE version_id=NEW.version_id AND item_id=NEW.item_id;
  IF d_tenant IS NULL OR m_tenant IS NULL OR v.version_id IS NULL THEN
    RAISE EXCEPTION 'decision evidence references missing decision, memory, or version' USING ERRCODE='23503';
  END IF;
  IF d_tenant<>m_tenant THEN
    RAISE EXCEPTION 'cross-tenant decision evidence forbidden' USING ERRCODE='42501';
  END IF;
  NEW.tenant_id := d_tenant;
  NEW.version_no := v.version_no;
  NEW.content_sha256 := v.content_sha256;
  NEW.category_snapshot := m_category;
  NEW.evidence_snapshot := jsonb_build_object(
    'category',m_category,'content_json',v.content_json,'content_text',v.content_text,
    'provenance',v.provenance,'source',v.source,'source_version',v.source_version,'tags',to_jsonb(v.tags)
  );
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_set_tenant_from_decision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  SELECT tenant_id INTO NEW.tenant_id FROM sovereign_decisions WHERE decision_id=NEW.decision_id;
  IF NEW.tenant_id IS NULL THEN RAISE EXCEPTION 'parent decision not visible' USING ERRCODE='23503'; END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_validate_decision_outcome_time() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE d_time timestamptz;
BEGIN
  SELECT occurred_at INTO d_time FROM sovereign_decisions WHERE decision_id=NEW.decision_id;
  IF d_time IS NULL THEN RAISE EXCEPTION 'parent decision missing' USING ERRCODE='23503'; END IF;
  IF NEW.occurred_at < d_time THEN RAISE EXCEPTION 'decision actual outcome cannot occur before the decision' USING ERRCODE='23514'; END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_validate_application_formal_decision() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE d_tenant text; DECLARE d_mission text;
BEGIN
  IF NEW.decision_id IS NULL THEN RETURN NEW; END IF;
  SELECT tenant_id,mission_id INTO d_tenant,d_mission FROM sovereign_decisions WHERE decision_id=NEW.decision_id;
  IF d_tenant IS NULL THEN
    RAISE EXCEPTION 'new application decision_id must reference a formal sovereign decision' USING ERRCODE='23503';
  END IF;
  IF NEW.mission_id IS NULL OR NEW.mission_id<>d_mission THEN
    RAISE EXCEPTION 'application mission_id must match formal decision mission' USING ERRCODE='23514';
  END IF;
  IF NEW.tenant_id IS DISTINCT FROM d_tenant THEN
    RAISE EXCEPTION 'application/decision tenant mismatch' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_resolve_decision_mission_anchor ON sovereign_decisions;
CREATE TRIGGER trg_resolve_decision_mission_anchor BEFORE INSERT ON sovereign_decisions FOR EACH ROW EXECUTE FUNCTION memory_resolve_decision_mission_anchor();
DROP TRIGGER IF EXISTS trg_validate_decision_evidence ON sovereign_decision_evidence;
CREATE TRIGGER trg_validate_decision_evidence BEFORE INSERT ON sovereign_decision_evidence FOR EACH ROW EXECUTE FUNCTION memory_validate_decision_evidence();
DROP TRIGGER IF EXISTS trg_set_tenant ON sovereign_decision_outcomes;
CREATE TRIGGER trg_set_tenant BEFORE INSERT ON sovereign_decision_outcomes FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_decision();
DROP TRIGGER IF EXISTS trg_validate_decision_outcome_time ON sovereign_decision_outcomes;
CREATE TRIGGER trg_validate_decision_outcome_time BEFORE INSERT ON sovereign_decision_outcomes FOR EACH ROW EXECUTE FUNCTION memory_validate_decision_outcome_time();
DROP TRIGGER IF EXISTS trg_set_tenant ON sovereign_decision_replays;
CREATE TRIGGER trg_set_tenant BEFORE INSERT ON sovereign_decision_replays FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_decision();
DROP TRIGGER IF EXISTS trg_validate_application_formal_decision ON memory_applications;
CREATE TRIGGER trg_validate_application_formal_decision BEFORE INSERT ON memory_applications FOR EACH ROW EXECUTE FUNCTION memory_validate_application_formal_decision();

DROP TRIGGER IF EXISTS trg_sovereign_decisions_append_only ON sovereign_decisions;
CREATE TRIGGER trg_sovereign_decisions_append_only BEFORE UPDATE OR DELETE ON sovereign_decisions FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
DROP TRIGGER IF EXISTS trg_sovereign_decision_evidence_append_only ON sovereign_decision_evidence;
CREATE TRIGGER trg_sovereign_decision_evidence_append_only BEFORE UPDATE OR DELETE ON sovereign_decision_evidence FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
DROP TRIGGER IF EXISTS trg_sovereign_decision_outcomes_append_only ON sovereign_decision_outcomes;
CREATE TRIGGER trg_sovereign_decision_outcomes_append_only BEFORE UPDATE OR DELETE ON sovereign_decision_outcomes FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
DROP TRIGGER IF EXISTS trg_sovereign_decision_replays_append_only ON sovereign_decision_replays;
CREATE TRIGGER trg_sovereign_decision_replays_append_only BEFORE UPDATE OR DELETE ON sovereign_decision_replays FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
DROP TRIGGER IF EXISTS trg_sovereign_decision_legacy_inventory_append_only ON sovereign_decision_legacy_inventory;
CREATE TRIGGER trg_sovereign_decision_legacy_inventory_append_only BEFORE UPDATE OR DELETE ON sovereign_decision_legacy_inventory FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['sovereign_decisions','sovereign_decision_evidence','sovereign_decision_outcomes','sovereign_decision_replays','sovereign_decision_legacy_inventory'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I',t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (memory_rls_visible(tenant_id)) WITH CHECK (memory_rls_visible(tenant_id))',t);
  END LOOP;
END $$;

GRANT SELECT,INSERT ON sovereign_decisions,sovereign_decision_evidence,sovereign_decision_outcomes,sovereign_decision_replays TO memory_app;
GRANT SELECT ON sovereign_decision_legacy_inventory TO memory_app;

INSERT INTO schema_meta(key,value) VALUES('decision_record_version','DR-1.0.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.18.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
