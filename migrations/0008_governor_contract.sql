ALTER TABLE memory_items
  ADD COLUMN IF NOT EXISTS validation_status text NOT NULL DEFAULT 'UNVALIDATED',
  ADD COLUMN IF NOT EXISTS governor_eligible boolean NOT NULL DEFAULT false;

ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS chk_memory_validation_status;
ALTER TABLE memory_items ADD CONSTRAINT chk_memory_validation_status
  CHECK(validation_status IN ('UNVALIDATED','VALIDATED','REJECTED'));

ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS chk_governor_eligible_project_only;
ALTER TABLE memory_items ADD CONSTRAINT chk_governor_eligible_project_only
  CHECK(
    governor_eligible = false
    OR (
      sharing_scope = 'PROJECT_SHARED'
      AND project_id IS NOT NULL
      AND validation_status = 'VALIDATED'
    )
  );

CREATE INDEX IF NOT EXISTS idx_memory_governor_eligible
ON memory_items(tenant_id,project_id,category,created_at DESC)
WHERE governor_eligible = true AND validation_status = 'VALIDATED';

ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS project_id text;
CREATE INDEX IF NOT EXISTS idx_checkpoints_project_mission
ON checkpoints(tenant_id,project_id,mission_id,step_index DESC,created_at DESC)
WHERE project_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS governor_project_bindings(
  tenant_id text NOT NULL,
  governor_id text NOT NULL,
  project_id text NOT NULL,
  contract_version text NOT NULL,
  access_key_sha256 text NOT NULL,
  status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','DISABLED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,governor_id)
);
ALTER TABLE governor_project_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE governor_project_bindings FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON governor_project_bindings;
CREATE POLICY tenant_isolation ON governor_project_bindings
USING(memory_rls_visible(tenant_id))
WITH CHECK(memory_rls_visible(tenant_id));

CREATE OR REPLACE FUNCTION prevent_governor_project_rebind() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.project_id IS DISTINCT FROM OLD.project_id THEN
    RAISE EXCEPTION 'governor project binding is immutable';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_prevent_governor_project_rebind ON governor_project_bindings;
CREATE TRIGGER trg_prevent_governor_project_rebind
BEFORE UPDATE ON governor_project_bindings
FOR EACH ROW EXECUTE FUNCTION prevent_governor_project_rebind();

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.8.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
