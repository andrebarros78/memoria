CREATE OR REPLACE FUNCTION memory_rls_visible(row_tenant text) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT row_tenant = current_setting('app.current_tenant', true)
      OR current_setting('app.current_tenant', true) = '__SYSTEM__'
$$;

ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';

CREATE INDEX IF NOT EXISTS idx_memory_items_tenant_ns ON memory_items(tenant_id,namespace,created_at DESC);

ALTER TABLE memory_versions ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';
CREATE INDEX IF NOT EXISTS idx_memory_versions_tenant_item ON memory_versions(tenant_id,item_id,version_no DESC);

ALTER TABLE memory_events ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';
CREATE INDEX IF NOT EXISTS idx_memory_events_tenant_item ON memory_events(tenant_id,item_id,event_seq);

ALTER TABLE memory_operator_state ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';

ALTER TABLE retention_holds ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';

ALTER TABLE memory_embeddings ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_tenant_model ON memory_embeddings(tenant_id,model_id,status);

ALTER TABLE retrieval_traces ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';
CREATE INDEX IF NOT EXISTS idx_retrieval_traces_tenant_created ON retrieval_traces(tenant_id,created_at DESC);

ALTER TABLE checkpoints ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';
CREATE INDEX IF NOT EXISTS idx_checkpoints_tenant_mission ON checkpoints(tenant_id,mission_id,step_index DESC);

ALTER TABLE sovereign_sessions ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';
CREATE INDEX IF NOT EXISTS idx_sovereign_sessions_tenant ON sovereign_sessions(tenant_id,updated_at DESC);

ALTER TABLE external_session_bindings ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';

ALTER TABLE session_checkpoints ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';

ALTER TABLE context_packs ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';

ALTER TABLE session_rotations ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';

ALTER TABLE idempotency_records ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'LEGACY';
ALTER TABLE idempotency_records DROP CONSTRAINT IF EXISTS idempotency_records_pkey;
ALTER TABLE idempotency_records ADD PRIMARY KEY(tenant_id,operation,idempotency_key);

CREATE OR REPLACE FUNCTION memory_set_tenant_from_context() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE v text;
BEGIN
  v := current_setting('app.current_tenant', true);
  IF NEW.tenant_id IS NULL OR NEW.tenant_id = '' THEN
    IF v IS NULL OR v = '' OR v = '__SYSTEM__' THEN NEW.tenant_id := 'LEGACY'; ELSE NEW.tenant_id := v; END IF;
  ELSIF v IS NOT NULL AND v <> '' AND v <> '__SYSTEM__' AND NEW.tenant_id <> v THEN
    RAISE EXCEPTION 'tenant mismatch' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_set_tenant_from_item() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  SELECT tenant_id INTO NEW.tenant_id FROM memory_items WHERE item_id=NEW.item_id;
  IF NEW.tenant_id IS NULL THEN RAISE EXCEPTION 'parent memory not visible'; END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_set_tenant_from_session() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  SELECT tenant_id INTO NEW.tenant_id FROM sovereign_sessions WHERE session_id=NEW.session_id;
  IF NEW.tenant_id IS NULL THEN RAISE EXCEPTION 'parent session not visible'; END IF;
  RETURN NEW;
END;
$$;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['memory_items','retrieval_traces','checkpoints','sovereign_sessions','idempotency_records'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS trg_set_tenant ON %I', t);
    EXECUTE format('CREATE TRIGGER trg_set_tenant BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_context()', t);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['memory_versions','memory_events','memory_operator_state','retention_holds','memory_embeddings'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS trg_set_tenant ON %I', t);
    EXECUTE format('CREATE TRIGGER trg_set_tenant BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_item()', t);
  END LOOP;
  FOREACH t IN ARRAY ARRAY['external_session_bindings','session_checkpoints','context_packs','session_rotations'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS trg_set_tenant ON %I', t);
    EXECUTE format('CREATE TRIGGER trg_set_tenant BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_session()', t);
  END LOOP;
END $$;

ALTER TABLE memory_items ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE memory_versions ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE memory_events ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE memory_operator_state ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE retention_holds ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE memory_embeddings ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE retrieval_traces ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE checkpoints ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE sovereign_sessions ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE external_session_bindings ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE session_checkpoints ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE context_packs ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE session_rotations ALTER COLUMN tenant_id DROP DEFAULT;
ALTER TABLE idempotency_records ALTER COLUMN tenant_id DROP DEFAULT;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'memory_items','memory_versions','memory_events','memory_operator_state','retention_holds',
    'memory_embeddings','retrieval_traces','checkpoints','sovereign_sessions','external_session_bindings',
    'session_checkpoints','context_packs','session_rotations','idempotency_records'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (memory_rls_visible(tenant_id)) WITH CHECK (memory_rls_visible(tenant_id))', t);
  END LOOP;
END $$;

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.6.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();


