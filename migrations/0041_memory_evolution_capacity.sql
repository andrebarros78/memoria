-- Memory Evolution & Capacity Foundation.
CREATE TABLE IF NOT EXISTS memory_capacity_snapshots(
  snapshot_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT current_setting('app.current_tenant',true),
  metrics jsonb NOT NULL,
  state text NOT NULL CHECK(state IN ('NORMAL','WARN','PROTECT')),
  reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS memory_evolution_proofs(
  proof_id text PRIMARY KEY,
  tenant_id text NOT NULL DEFAULT current_setting('app.current_tenant',true),
  migration_version text NOT NULL,
  candidate_ref text NOT NULL,
  proof jsonb NOT NULL,
  status text NOT NULL CHECK(status IN ('PASS','DENY')),
  reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
  evidence_sha256 text NOT NULL CHECK(evidence_sha256 ~ '^[0-9a-f]{64}$'),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION memory_evolution_evidence_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'memory evolution evidence is append-only' USING ERRCODE='55000'; END; $$;
DROP TRIGGER IF EXISTS trg_memory_capacity_snapshots_append_only ON memory_capacity_snapshots;
CREATE TRIGGER trg_memory_capacity_snapshots_append_only BEFORE UPDATE OR DELETE ON memory_capacity_snapshots FOR EACH ROW EXECUTE FUNCTION memory_evolution_evidence_append_only();
DROP TRIGGER IF EXISTS trg_memory_evolution_proofs_append_only ON memory_evolution_proofs;
CREATE TRIGGER trg_memory_evolution_proofs_append_only BEFORE UPDATE OR DELETE ON memory_evolution_proofs FOR EACH ROW EXECUTE FUNCTION memory_evolution_evidence_append_only();
ALTER TABLE memory_capacity_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_capacity_snapshots FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON memory_capacity_snapshots;
CREATE POLICY tenant_isolation ON memory_capacity_snapshots USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));
ALTER TABLE memory_evolution_proofs ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_evolution_proofs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON memory_evolution_proofs;
CREATE POLICY tenant_isolation ON memory_evolution_proofs USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));
CREATE INDEX IF NOT EXISTS idx_memory_capacity_created ON memory_capacity_snapshots(tenant_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_evolution_candidate ON memory_evolution_proofs(tenant_id,candidate_ref,created_at DESC);
INSERT INTO schema_meta(key,value) VALUES('evolution_capacity_contract_version','EC-1.0.0') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();