ALTER TABLE memory_items
  ADD COLUMN IF NOT EXISTS sharing_scope text NOT NULL DEFAULT 'SYSTEM_SHARED',
  ADD COLUMN IF NOT EXISTS owner_user_id text,
  ADD COLUMN IF NOT EXISTS owner_agent_id text,
  ADD COLUMN IF NOT EXISTS project_id text,
  ADD COLUMN IF NOT EXISTS team_id text,
  ADD COLUMN IF NOT EXISTS organization_id text;

ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS chk_memory_items_sharing_scope;
ALTER TABLE memory_items ADD CONSTRAINT chk_memory_items_sharing_scope CHECK(
  sharing_scope IN ('PRIVATE_USER','PROJECT_SHARED','AGENT_PRIVATE','AGENT_TEAM','SYSTEM_SHARED','ORGANIZATION_SHARED')
);
CREATE INDEX IF NOT EXISTS idx_memory_items_sharing_scope ON memory_items(tenant_id,sharing_scope);
CREATE INDEX IF NOT EXISTS idx_memory_items_project ON memory_items(tenant_id,project_id) WHERE project_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memory_items_agent ON memory_items(tenant_id,owner_agent_id) WHERE owner_agent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memory_items_team ON memory_items(tenant_id,team_id) WHERE team_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memory_items_org ON memory_items(tenant_id,organization_id) WHERE organization_id IS NOT NULL;

CREATE OR REPLACE FUNCTION memory_agent_visible(
  row_scope text,
  row_owner_user text,
  row_owner_agent text,
  row_project text,
  row_team text,
  row_org text
) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT
    current_setting('app.current_tenant', true) = '__SYSTEM__'
    OR current_setting('app.current_agent', true) = '__SYSTEM__'
    OR CASE row_scope
      WHEN 'SYSTEM_SHARED' THEN true
      WHEN 'PRIVATE_USER' THEN row_owner_user IS NOT NULL AND row_owner_user = current_setting('app.current_user_id', true)
      WHEN 'PROJECT_SHARED' THEN row_project IS NOT NULL AND row_project = current_setting('app.current_project', true)
      WHEN 'AGENT_PRIVATE' THEN row_owner_agent IS NOT NULL AND row_owner_agent = current_setting('app.current_agent', true)
      WHEN 'AGENT_TEAM' THEN row_team IS NOT NULL AND row_team = current_setting('app.current_team', true)
      WHEN 'ORGANIZATION_SHARED' THEN row_org IS NOT NULL AND row_org = current_setting('app.current_org', true)
      ELSE false
    END
$$;

DROP POLICY IF EXISTS tenant_isolation ON memory_items;
DROP POLICY IF EXISTS tenant_and_agent_isolation ON memory_items;
CREATE POLICY tenant_and_agent_isolation ON memory_items
USING (
  memory_rls_visible(tenant_id)
  AND memory_agent_visible(sharing_scope,owner_user_id,owner_agent_id,project_id,team_id,organization_id)
)
WITH CHECK (
  memory_rls_visible(tenant_id)
  AND memory_agent_visible(sharing_scope,owner_user_id,owner_agent_id,project_id,team_id,organization_id)
);

ALTER TABLE memory_items ALTER COLUMN sharing_scope DROP DEFAULT;

CREATE TABLE IF NOT EXISTS agent_leases(
  tenant_id text NOT NULL,
  lease_key text NOT NULL,
  owner_agent_id text NOT NULL,
  lease_version bigint NOT NULL CHECK(lease_version > 0),
  fencing_token bigint NOT NULL CHECK(fencing_token > 0),
  expires_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(tenant_id,lease_key)
);
ALTER TABLE agent_leases ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_leases FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON agent_leases;
CREATE POLICY tenant_isolation ON agent_leases USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));

CREATE TABLE IF NOT EXISTS memory_outbox(
  outbox_id bigserial PRIMARY KEY,
  tenant_id text NOT NULL,
  event_id text NOT NULL UNIQUE REFERENCES memory_events(event_id) ON DELETE RESTRICT,
  topic text NOT NULL,
  payload jsonb NOT NULL,
  status text NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','PUBLISHED','FAILED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_memory_outbox_pending ON memory_outbox(status,outbox_id) WHERE status='PENDING';
ALTER TABLE memory_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_outbox FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON memory_outbox;
CREATE POLICY tenant_isolation ON memory_outbox USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));

CREATE OR REPLACE FUNCTION enqueue_memory_event_outbox() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO memory_outbox(tenant_id,event_id,topic,payload)
  VALUES(NEW.tenant_id,NEW.event_id,'memory.event',jsonb_build_object(
    'event_id',NEW.event_id,
    'item_id',NEW.item_id,
    'version_id',NEW.version_id,
    'event_type',NEW.event_type,
    'request_sha256',NEW.request_sha256,
    'created_at',NEW.created_at
  ))
  ON CONFLICT(event_id) DO NOTHING;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_memory_events_outbox ON memory_events;
CREATE TRIGGER trg_memory_events_outbox AFTER INSERT ON memory_events
FOR EACH ROW EXECUTE FUNCTION enqueue_memory_event_outbox();

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.7.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
