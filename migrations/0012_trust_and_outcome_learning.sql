CREATE TABLE IF NOT EXISTS memory_validations(
  validation_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  version_id text NOT NULL REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  version_no integer NOT NULL CHECK(version_no > 0),
  content_sha256 text NOT NULL,
  status text NOT NULL CHECK(status IN ('VALIDATED','REJECTED')),
  governor_eligible boolean NOT NULL DEFAULT false,
  validator_client_id text NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_validations_item ON memory_validations(tenant_id,item_id,version_no DESC);

CREATE TABLE IF NOT EXISTS memory_applications(
  application_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  version_id text NOT NULL REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  content_sha256 text NOT NULL,
  mission_id text,
  decision_id text,
  action_ref text NOT NULL,
  context jsonb NOT NULL DEFAULT '{}'::jsonb,
  applied_by_client_id text NOT NULL,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_applications_item ON memory_applications(tenant_id,item_id,observed_at DESC);

CREATE TABLE IF NOT EXISTS memory_outcomes(
  outcome_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  application_id text NOT NULL UNIQUE REFERENCES memory_applications(application_id) ON DELETE RESTRICT,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  success boolean NOT NULL,
  outcome_type text NOT NULL,
  expected jsonb NOT NULL DEFAULT '{}'::jsonb,
  actual jsonb NOT NULL DEFAULT '{}'::jsonb,
  confidence_delta double precision NOT NULL DEFAULT 0 CHECK(confidence_delta >= -1 AND confidence_delta <= 1),
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_outcomes_item ON memory_outcomes(tenant_id,item_id,observed_at DESC);

CREATE TABLE IF NOT EXISTS memory_experience_edges(
  edge_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  from_type text NOT NULL,
  from_id text NOT NULL,
  relation text NOT NULL CHECK(relation IN ('BASED_ON','USED','PRODUCED','CONFIRMED','CONTRADICTED','INCREASED_CONFIDENCE','DECREASED_CONFIDENCE')),
  to_type text NOT NULL,
  to_id text NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at timestamptz NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_experience_edges_from ON memory_experience_edges(tenant_id,from_type,from_id,occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_experience_edges_to ON memory_experience_edges(tenant_id,to_type,to_id,occurred_at DESC);

DROP TRIGGER IF EXISTS trg_memory_validations_append_only ON memory_validations;
CREATE TRIGGER trg_memory_validations_append_only BEFORE UPDATE OR DELETE ON memory_validations
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
DROP TRIGGER IF EXISTS trg_memory_applications_append_only ON memory_applications;
CREATE TRIGGER trg_memory_applications_append_only BEFORE UPDATE OR DELETE ON memory_applications
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
DROP TRIGGER IF EXISTS trg_memory_outcomes_append_only ON memory_outcomes;
CREATE TRIGGER trg_memory_outcomes_append_only BEFORE UPDATE OR DELETE ON memory_outcomes
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
DROP TRIGGER IF EXISTS trg_memory_experience_edges_append_only ON memory_experience_edges;
CREATE TRIGGER trg_memory_experience_edges_append_only BEFORE UPDATE OR DELETE ON memory_experience_edges
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

DROP TRIGGER IF EXISTS trg_set_tenant ON memory_validations;
CREATE TRIGGER trg_set_tenant BEFORE INSERT ON memory_validations FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_item();
DROP TRIGGER IF EXISTS trg_set_tenant ON memory_applications;
CREATE TRIGGER trg_set_tenant BEFORE INSERT ON memory_applications FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_item();
DROP TRIGGER IF EXISTS trg_set_tenant ON memory_outcomes;
CREATE TRIGGER trg_set_tenant BEFORE INSERT ON memory_outcomes FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_item();
DROP TRIGGER IF EXISTS trg_set_tenant ON memory_experience_edges;
CREATE TRIGGER trg_set_tenant BEFORE INSERT ON memory_experience_edges FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_context();

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['memory_validations','memory_applications','memory_outcomes','memory_experience_edges'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (memory_rls_visible(tenant_id)) WITH CHECK (memory_rls_visible(tenant_id))', t);
  END LOOP;
END $$;

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.11.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
