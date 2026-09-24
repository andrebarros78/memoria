CREATE TABLE IF NOT EXISTS memory_derived_artifacts(
  artifact_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  artifact_type text NOT NULL,
  artifact_ref text NOT NULL,
  artifact_sha256 text,
  status text NOT NULL DEFAULT 'READY' CHECK(status IN ('READY','STALE','INVALID')),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  invalidation_reason text,
  stale_source_version_id text REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  staled_at timestamptz,
  invalidated_at timestamptz
);
CREATE INDEX IF NOT EXISTS idx_memory_derived_artifacts_tenant_type_status
  ON memory_derived_artifacts(tenant_id,artifact_type,status,updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_derived_artifacts_ref
  ON memory_derived_artifacts(tenant_id,artifact_type,artifact_ref);

CREATE TABLE IF NOT EXISTS memory_artifact_dependencies(
  dependency_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  artifact_id text NOT NULL REFERENCES memory_derived_artifacts(artifact_id) ON DELETE RESTRICT,
  source_item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  source_version_id text NOT NULL REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  source_content_sha256 text NOT NULL,
  dependency_kind text NOT NULL DEFAULT 'DERIVED_FROM',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(artifact_id,source_version_id,dependency_kind)
);
CREATE INDEX IF NOT EXISTS idx_memory_artifact_dependencies_source
  ON memory_artifact_dependencies(tenant_id,source_item_id,source_version_id);
CREATE INDEX IF NOT EXISTS idx_memory_artifact_dependencies_artifact
  ON memory_artifact_dependencies(tenant_id,artifact_id);

CREATE TABLE IF NOT EXISTS memory_artifact_state_events(
  seq bigserial PRIMARY KEY,
  tenant_id text NOT NULL,
  artifact_id text NOT NULL REFERENCES memory_derived_artifacts(artifact_id) ON DELETE RESTRICT,
  old_status text,
  new_status text NOT NULL,
  reason text,
  source_version_id text REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_artifact_state_events_artifact
  ON memory_artifact_state_events(tenant_id,artifact_id,seq DESC);

CREATE OR REPLACE FUNCTION memory_validate_derived_artifact_tenant() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE ctx text;
BEGIN
  ctx := current_setting('app.current_tenant', true);
  IF NEW.tenant_id IS NULL OR NEW.tenant_id = '' THEN
    RAISE EXCEPTION 'derived artifact tenant_id is required' USING ERRCODE='23502';
  END IF;
  IF ctx IS NOT NULL AND ctx <> '' AND ctx <> '__SYSTEM__' AND NEW.tenant_id <> ctx THEN
    RAISE EXCEPTION 'derived artifact tenant mismatch' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_set_artifact_dependency_tenant() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE artifact_tenant text;
DECLARE source_tenant text;
BEGIN
  SELECT tenant_id INTO artifact_tenant FROM memory_derived_artifacts WHERE artifact_id=NEW.artifact_id;
  SELECT tenant_id INTO source_tenant FROM memory_items WHERE item_id=NEW.source_item_id;
  IF artifact_tenant IS NULL OR source_tenant IS NULL THEN
    RAISE EXCEPTION 'artifact or source memory not visible';
  END IF;
  IF artifact_tenant <> source_tenant THEN
    RAISE EXCEPTION 'cross-tenant derived dependency forbidden' USING ERRCODE='42501';
  END IF;
  NEW.tenant_id := artifact_tenant;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_set_artifact_event_tenant() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  SELECT tenant_id INTO NEW.tenant_id FROM memory_derived_artifacts WHERE artifact_id=NEW.artifact_id;
  IF NEW.tenant_id IS NULL THEN RAISE EXCEPTION 'artifact not visible'; END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_record_artifact_state_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IS DISTINCT FROM NEW.status THEN
    INSERT INTO memory_artifact_state_events(
      tenant_id,artifact_id,old_status,new_status,reason,source_version_id
    ) VALUES(
      NEW.tenant_id,NEW.artifact_id,OLD.status,NEW.status,NEW.invalidation_reason,NEW.stale_source_version_id
    );
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION memory_invalidate_derived_on_new_version() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.previous_version_id IS NULL THEN
    RETURN NEW;
  END IF;

  UPDATE memory_derived_artifacts a
     SET status='STALE',
         invalidation_reason='SOURCE_VERSION_SUPERSEDED',
         stale_source_version_id=NEW.previous_version_id,
         staled_at=COALESCE(a.staled_at,now()),
         updated_at=now()
   WHERE a.status='READY'
     AND EXISTS(
       SELECT 1 FROM memory_artifact_dependencies d
        WHERE d.artifact_id=a.artifact_id
          AND d.source_version_id=NEW.previous_version_id
     );

  UPDATE memory_embeddings
     SET status='STALE',updated_at=now()
   WHERE item_id=NEW.item_id
     AND content_sha256<>NEW.content_sha256
     AND status='READY';

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_validate_derived_artifact_tenant ON memory_derived_artifacts;
CREATE TRIGGER trg_validate_derived_artifact_tenant
BEFORE INSERT OR UPDATE ON memory_derived_artifacts
FOR EACH ROW EXECUTE FUNCTION memory_validate_derived_artifact_tenant();

DROP TRIGGER IF EXISTS trg_set_artifact_dependency_tenant ON memory_artifact_dependencies;
CREATE TRIGGER trg_set_artifact_dependency_tenant
BEFORE INSERT ON memory_artifact_dependencies
FOR EACH ROW EXECUTE FUNCTION memory_set_artifact_dependency_tenant();

DROP TRIGGER IF EXISTS trg_set_artifact_event_tenant ON memory_artifact_state_events;
CREATE TRIGGER trg_set_artifact_event_tenant
BEFORE INSERT ON memory_artifact_state_events
FOR EACH ROW EXECUTE FUNCTION memory_set_artifact_event_tenant();

DROP TRIGGER IF EXISTS trg_artifact_state_change ON memory_derived_artifacts;
CREATE TRIGGER trg_artifact_state_change
AFTER UPDATE OF status ON memory_derived_artifacts
FOR EACH ROW EXECUTE FUNCTION memory_record_artifact_state_change();

DROP TRIGGER IF EXISTS trg_invalidate_derived_on_new_version ON memory_versions;
CREATE TRIGGER trg_invalidate_derived_on_new_version
AFTER INSERT ON memory_versions
FOR EACH ROW EXECUTE FUNCTION memory_invalidate_derived_on_new_version();

DROP TRIGGER IF EXISTS trg_memory_artifact_state_events_append_only ON memory_artifact_state_events;
CREATE TRIGGER trg_memory_artifact_state_events_append_only
BEFORE UPDATE OR DELETE ON memory_artifact_state_events
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['memory_derived_artifacts','memory_artifact_dependencies','memory_artifact_state_events'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I',t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (memory_rls_visible(tenant_id)) WITH CHECK (memory_rls_visible(tenant_id))',t);
  END LOOP;
END $$;

-- Backfill exact embedding dependencies by content hash.
INSERT INTO memory_derived_artifacts(
  artifact_id,tenant_id,artifact_type,artifact_ref,artifact_sha256,status,metadata,created_at,updated_at
)
SELECT
  'art-emb-'||substr(md5(e.tenant_id||':'||e.item_id||':'||e.model_id||':'||v.version_id),1,32),
  e.tenant_id,'EMBEDDING',e.item_id||':'||e.model_id,e.content_sha256,
  CASE WHEN e.status='READY' THEN 'READY' WHEN e.status='STALE' THEN 'STALE' ELSE 'INVALID' END,
  jsonb_build_object('model_id',e.model_id,'dimensions',e.dimensions,'backfill','0015'),
  e.updated_at,e.updated_at
FROM memory_embeddings e
JOIN memory_versions v ON v.item_id=e.item_id AND v.content_sha256=e.content_sha256
ON CONFLICT(artifact_id) DO NOTHING;

INSERT INTO memory_artifact_dependencies(
  dependency_id,tenant_id,artifact_id,source_item_id,source_version_id,source_content_sha256,dependency_kind
)
SELECT
  'dep-'||substr(md5(a.artifact_id||':'||v.version_id),1,32),
  e.tenant_id,a.artifact_id,e.item_id,v.version_id,v.content_sha256,'DERIVED_FROM'
FROM memory_embeddings e
JOIN memory_versions v ON v.item_id=e.item_id AND v.content_sha256=e.content_sha256
JOIN memory_derived_artifacts a
  ON a.artifact_id='art-emb-'||substr(md5(e.tenant_id||':'||e.item_id||':'||e.model_id||':'||v.version_id),1,32)
ON CONFLICT(artifact_id,source_version_id,dependency_kind) DO NOTHING;

-- Backfill retrieval traces using exact content hashes already recorded in selected JSON.
INSERT INTO memory_derived_artifacts(
  artifact_id,tenant_id,artifact_type,artifact_ref,artifact_sha256,status,metadata,created_at,updated_at
)
SELECT
  'art-ret-'||substr(md5(r.tenant_id||':'||r.trace_id),1,32),
  r.tenant_id,'RETRIEVAL_TRACE',r.trace_id,NULL,'READY',
  jsonb_build_object('selected_count',jsonb_array_length(r.selected),'backfill','0015'),
  r.created_at,r.created_at
FROM retrieval_traces r
WHERE jsonb_typeof(r.selected)='array'
ON CONFLICT(artifact_id) DO NOTHING;

WITH refs AS (
  SELECT r.tenant_id,r.trace_id,e->>'item_id' AS item_id,e->>'content_sha256' AS content_sha256
  FROM retrieval_traces r
  CROSS JOIN LATERAL jsonb_array_elements(r.selected) e
  WHERE e ? 'item_id' AND e ? 'content_sha256'
)
INSERT INTO memory_artifact_dependencies(
  dependency_id,tenant_id,artifact_id,source_item_id,source_version_id,source_content_sha256,dependency_kind
)
SELECT
  'dep-'||substr(md5(a.artifact_id||':'||v.version_id),1,32),
  refs.tenant_id,a.artifact_id,refs.item_id,v.version_id,v.content_sha256,'DERIVED_FROM'
FROM refs
JOIN memory_versions v ON v.item_id=refs.item_id AND v.content_sha256=refs.content_sha256
JOIN memory_derived_artifacts a ON a.artifact_id='art-ret-'||substr(md5(refs.tenant_id||':'||refs.trace_id),1,32)
ON CONFLICT(artifact_id,source_version_id,dependency_kind) DO NOTHING;

-- Backfill context packs by the version that existed when the pack was created.
INSERT INTO memory_derived_artifacts(
  artifact_id,tenant_id,artifact_type,artifact_ref,artifact_sha256,status,metadata,created_at,updated_at
)
SELECT
  'art-ctx-'||substr(md5(c.tenant_id||':'||c.context_pack_id),1,32),
  c.tenant_id,'CONTEXT_PACK',c.context_pack_id,c.context_sha256,'READY',
  jsonb_build_object('session_id',c.session_id,'checkpoint_id',c.checkpoint_id,'backfill','0015'),
  c.created_at,c.created_at
FROM context_packs c
ON CONFLICT(artifact_id) DO NOTHING;

WITH refs AS (
  SELECT c.tenant_id,c.context_pack_id,c.created_at,unnest(c.required_memory_ids) AS item_id
  FROM context_packs c
)
INSERT INTO memory_artifact_dependencies(
  dependency_id,tenant_id,artifact_id,source_item_id,source_version_id,source_content_sha256,dependency_kind
)
SELECT
  'dep-'||substr(md5(a.artifact_id||':'||v.version_id),1,32),
  refs.tenant_id,a.artifact_id,refs.item_id,v.version_id,v.content_sha256,'DERIVED_FROM'
FROM refs
JOIN LATERAL (
  SELECT version_id,content_sha256
  FROM memory_versions v
  WHERE v.item_id=refs.item_id AND v.created_at<=refs.created_at
  ORDER BY v.created_at DESC,v.version_no DESC LIMIT 1
) v ON true
JOIN memory_derived_artifacts a ON a.artifact_id='art-ctx-'||substr(md5(refs.tenant_id||':'||refs.context_pack_id),1,32)
ON CONFLICT(artifact_id,source_version_id,dependency_kind) DO NOTHING;

-- Backfill session checkpoints and generic checkpoints when required_memory_ids are present.
INSERT INTO memory_derived_artifacts(
  artifact_id,tenant_id,artifact_type,artifact_ref,artifact_sha256,status,metadata,created_at,updated_at
)
SELECT
  'art-scp-'||substr(md5(s.tenant_id||':'||s.checkpoint_id),1,32),
  s.tenant_id,'SESSION_CHECKPOINT',s.checkpoint_id,s.state_sha256,'READY',
  jsonb_build_object('session_id',s.session_id,'backfill','0015'),s.created_at,s.created_at
FROM session_checkpoints s
WHERE jsonb_typeof(COALESCE(s.state_json->'required_memory_ids','[]'::jsonb))='array'
ON CONFLICT(artifact_id) DO NOTHING;

WITH refs AS (
  SELECT s.tenant_id,s.checkpoint_id,s.created_at,jsonb_array_elements_text(COALESCE(s.state_json->'required_memory_ids','[]'::jsonb)) AS item_id
  FROM session_checkpoints s
)
INSERT INTO memory_artifact_dependencies(
  dependency_id,tenant_id,artifact_id,source_item_id,source_version_id,source_content_sha256,dependency_kind
)
SELECT
  'dep-'||substr(md5(a.artifact_id||':'||v.version_id),1,32),refs.tenant_id,a.artifact_id,refs.item_id,v.version_id,v.content_sha256,'DERIVED_FROM'
FROM refs
JOIN LATERAL (
  SELECT version_id,content_sha256 FROM memory_versions v
  WHERE v.item_id=refs.item_id AND v.created_at<=refs.created_at
  ORDER BY v.created_at DESC,v.version_no DESC LIMIT 1
) v ON true
JOIN memory_derived_artifacts a ON a.artifact_id='art-scp-'||substr(md5(refs.tenant_id||':'||refs.checkpoint_id),1,32)
ON CONFLICT(artifact_id,source_version_id,dependency_kind) DO NOTHING;

INSERT INTO memory_derived_artifacts(
  artifact_id,tenant_id,artifact_type,artifact_ref,artifact_sha256,status,metadata,created_at,updated_at
)
SELECT
  'art-cp-'||substr(md5(c.tenant_id||':'||c.checkpoint_id),1,32),
  c.tenant_id,'CHECKPOINT',c.checkpoint_id,c.state_sha256,'READY',
  jsonb_build_object('mission_id',c.mission_id,'backfill','0015'),c.created_at,c.created_at
FROM checkpoints c
WHERE jsonb_typeof(COALESCE(c.state_json->'required_memory_ids','[]'::jsonb))='array'
ON CONFLICT(artifact_id) DO NOTHING;

WITH refs AS (
  SELECT c.tenant_id,c.checkpoint_id,c.created_at,jsonb_array_elements_text(COALESCE(c.state_json->'required_memory_ids','[]'::jsonb)) AS item_id
  FROM checkpoints c
)
INSERT INTO memory_artifact_dependencies(
  dependency_id,tenant_id,artifact_id,source_item_id,source_version_id,source_content_sha256,dependency_kind
)
SELECT
  'dep-'||substr(md5(a.artifact_id||':'||v.version_id),1,32),refs.tenant_id,a.artifact_id,refs.item_id,v.version_id,v.content_sha256,'DERIVED_FROM'
FROM refs
JOIN LATERAL (
  SELECT version_id,content_sha256 FROM memory_versions v
  WHERE v.item_id=refs.item_id AND v.created_at<=refs.created_at
  ORDER BY v.created_at DESC,v.version_no DESC LIMIT 1
) v ON true
JOIN memory_derived_artifacts a ON a.artifact_id='art-cp-'||substr(md5(refs.tenant_id||':'||refs.checkpoint_id),1,32)
ON CONFLICT(artifact_id,source_version_id,dependency_kind) DO NOTHING;

-- Mark historical artifacts stale when any recorded dependency is no longer the item's current version.
WITH stale AS (
  SELECT DISTINCT ON (d.artifact_id) d.artifact_id,d.source_version_id
  FROM memory_artifact_dependencies d
  JOIN memory_versions cur ON cur.item_id=d.source_item_id
  WHERE cur.version_no=(SELECT max(v2.version_no) FROM memory_versions v2 WHERE v2.item_id=d.source_item_id)
    AND cur.version_id<>d.source_version_id
  ORDER BY d.artifact_id,d.source_version_id
)
UPDATE memory_derived_artifacts a
SET status='STALE',invalidation_reason='SOURCE_VERSION_SUPERSEDED_BACKFILL',
    stale_source_version_id=stale.source_version_id,staled_at=COALESCE(a.staled_at,now()),updated_at=now()
FROM stale
WHERE stale.artifact_id=a.artifact_id AND a.status='READY';

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.14.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
