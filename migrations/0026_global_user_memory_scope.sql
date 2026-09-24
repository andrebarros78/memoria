-- P11: separate semantic memory scope from sharing/ACL scope.

ALTER TABLE memory_items
  ADD COLUMN memory_scope text,
  ADD COLUMN memory_scope_ref text;

WITH migrated AS (
  UPDATE memory_items
  SET memory_scope='GLOBAL_USER', memory_scope_ref=NULL
  WHERE memory_scope IS NULL
  RETURNING 1
)
INSERT INTO schema_meta(key,value)
SELECT 'memory_scope_legacy_backfill_count',count(*)::text FROM migrated
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();

ALTER TABLE memory_items ALTER COLUMN memory_scope SET NOT NULL;
ALTER TABLE memory_items ALTER COLUMN memory_scope SET DEFAULT 'GLOBAL_USER';
ALTER TABLE memory_items DROP CONSTRAINT IF EXISTS chk_memory_items_memory_scope;
ALTER TABLE memory_items ADD CONSTRAINT chk_memory_items_memory_scope CHECK(
  memory_scope IN ('GLOBAL_USER','PROJECT','MISSION','SESSION')
  AND (
    (memory_scope='GLOBAL_USER' AND memory_scope_ref IS NULL)
    OR
    (memory_scope IN ('PROJECT','MISSION','SESSION') AND memory_scope_ref IS NOT NULL AND length(btrim(memory_scope_ref))>0)
  )
);
CREATE INDEX idx_memory_items_memory_scope ON memory_items(tenant_id,memory_scope,memory_scope_ref);

COMMENT ON COLUMN memory_items.memory_scope IS 'Semantic context only: GLOBAL_USER|PROJECT|MISSION|SESSION. Not an ACL.';
COMMENT ON COLUMN memory_items.memory_scope_ref IS 'Semantic scope reference; null for GLOBAL_USER; required for PROJECT/MISSION/SESSION.';
COMMENT ON COLUMN memory_items.sharing_scope IS 'Access-control sharing scope. Independent from semantic memory_scope.';

CREATE OR REPLACE FUNCTION memory_validate_memory_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.memory_scope := upper(btrim(COALESCE(NEW.memory_scope,'GLOBAL_USER')));
  IF NEW.memory_scope NOT IN ('GLOBAL_USER','PROJECT','MISSION','SESSION') THEN
    RAISE EXCEPTION 'invalid memory_scope: %',NEW.memory_scope USING ERRCODE='23514';
  END IF;
  IF NEW.memory_scope='GLOBAL_USER' THEN
    IF NEW.memory_scope_ref IS NOT NULL AND length(btrim(NEW.memory_scope_ref))>0 THEN
      RAISE EXCEPTION 'GLOBAL_USER memory_scope forbids memory_scope_ref' USING ERRCODE='23514';
    END IF;
    NEW.memory_scope_ref := NULL;
  ELSE
    NEW.memory_scope_ref := NULLIF(btrim(NEW.memory_scope_ref),'');
    IF NEW.memory_scope_ref IS NULL THEN
      RAISE EXCEPTION '% memory_scope requires memory_scope_ref',NEW.memory_scope USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_guard_memory_scope_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.memory_scope IS DISTINCT FROM NEW.memory_scope OR OLD.memory_scope_ref IS DISTINCT FROM NEW.memory_scope_ref THEN
    RAISE EXCEPTION 'memory_scope is immutable after memory creation' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_memory_scope ON memory_items;
CREATE TRIGGER trg_validate_memory_scope BEFORE INSERT OR UPDATE OF memory_scope,memory_scope_ref ON memory_items
FOR EACH ROW EXECUTE FUNCTION memory_validate_memory_scope();
DROP TRIGGER IF EXISTS trg_guard_memory_scope_update ON memory_items;
CREATE TRIGGER trg_guard_memory_scope_update BEFORE UPDATE OF memory_scope,memory_scope_ref ON memory_items
FOR EACH ROW EXECUTE FUNCTION memory_guard_memory_scope_update();

CREATE OR REPLACE FUNCTION memory_scope_matches_context(
  row_scope text,
  row_scope_ref text,
  context_project text,
  context_mission text,
  context_session text
) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE row_scope
    WHEN 'GLOBAL_USER' THEN true
    WHEN 'PROJECT' THEN row_scope_ref IS NOT NULL AND row_scope_ref = NULLIF(context_project,'')
    WHEN 'MISSION' THEN row_scope_ref IS NOT NULL AND row_scope_ref = NULLIF(context_mission,'')
    WHEN 'SESSION' THEN row_scope_ref IS NOT NULL AND row_scope_ref = NULLIF(context_session,'')
    ELSE false
  END
$$;

-- Re-assert ACL policy intentionally without memory_scope: semantic scope is not an authorization primitive.
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

INSERT INTO schema_meta(key,value) VALUES('memory_scope_version','MS-1.0.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
INSERT INTO schema_meta(key,value) VALUES('memory_scope_canonical_global','GLOBAL_USER')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
INSERT INTO schema_meta(key,value) VALUES('memory_scope_general_label','Memória Geral')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.19.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
