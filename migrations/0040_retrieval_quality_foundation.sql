-- Retrieval Quality Foundation: versioned golden sets and append-only evaluation runs.
CREATE TABLE IF NOT EXISTS retrieval_quality_golden_sets(
  golden_set_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT current_setting('app.current_tenant',true),
  name text NOT NULL,
  version integer NOT NULL CHECK(version > 0),
  definition jsonb NOT NULL,
  definition_sha256 text NOT NULL CHECK(definition_sha256 ~ '^[0-9a-f]{64}$'),
  status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','RETIRED')),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(tenant_id,name,version)
);
CREATE TABLE IF NOT EXISTS retrieval_quality_runs(
  run_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT current_setting('app.current_tenant',true),
  golden_set_id text REFERENCES retrieval_quality_golden_sets(golden_set_id) ON DELETE RESTRICT,
  candidate_ref text NOT NULL,
  metrics jsonb NOT NULL,
  gate text NOT NULL CHECK(gate IN ('PASS','DENY')),
  evidence_sha256 text NOT NULL CHECK(evidence_sha256 ~ '^[0-9a-f]{64}$'),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION retrieval_quality_runs_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'retrieval quality runs are append-only' USING ERRCODE='55000'; END; $$;
DROP TRIGGER IF EXISTS trg_retrieval_quality_runs_append_only ON retrieval_quality_runs;
CREATE TRIGGER trg_retrieval_quality_runs_append_only BEFORE UPDATE OR DELETE ON retrieval_quality_runs FOR EACH ROW EXECUTE FUNCTION retrieval_quality_runs_append_only();
ALTER TABLE retrieval_quality_golden_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE retrieval_quality_golden_sets FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON retrieval_quality_golden_sets;
CREATE POLICY tenant_isolation ON retrieval_quality_golden_sets USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));
ALTER TABLE retrieval_quality_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE retrieval_quality_runs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON retrieval_quality_runs;
CREATE POLICY tenant_isolation ON retrieval_quality_runs USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));
CREATE INDEX IF NOT EXISTS idx_retrieval_quality_runs_set_created ON retrieval_quality_runs(golden_set_id,created_at DESC);
INSERT INTO schema_meta(key,value) VALUES('retrieval_quality_contract_version','RQ-1.0.0') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
