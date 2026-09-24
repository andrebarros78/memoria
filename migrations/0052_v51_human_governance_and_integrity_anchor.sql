-- V5.1 closure: human operational governance + cryptographic integrity anchoring.
-- This migration only expands the schema. Existing canonical history is not rewritten.

CREATE TABLE IF NOT EXISTS memory_scopes(
  scope_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  scope_type text NOT NULL CHECK(scope_type IN ('GLOBAL_USER','PROJECT','MISSION','SESSION')),
  parent_scope_id text REFERENCES memory_scopes(scope_id) ON DELETE RESTRICT,
  user_id text,
  project_id text,
  mission_id text,
  session_id text,
  display_name text NOT NULL CHECK(length(btrim(display_name)) BETWEEN 1 AND 240),
  status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','ARCHIVED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(tenant_id,scope_type,project_id,mission_id,session_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_scopes_tree ON memory_scopes(tenant_id,parent_scope_id,scope_type,status);
CREATE INDEX IF NOT EXISTS idx_memory_scopes_project ON memory_scopes(tenant_id,project_id,scope_type);

CREATE TABLE IF NOT EXISTS memory_display_metadata(
  display_metadata_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  memory_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  display_version integer NOT NULL CHECK(display_version >= 1),
  human_title text NOT NULL CHECK(length(btrim(human_title)) BETWEEN 1 AND 300),
  human_summary text NOT NULL CHECK(length(btrim(human_summary)) BETWEEN 1 AND 1200),
  source_context_summary text,
  topic_tags_jsonb jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(topic_tags_jsonb)='array'),
  source_kind text NOT NULL DEFAULT 'MEMORY',
  source_label text,
  language text NOT NULL DEFAULT 'pt-BR',
  generated_by text NOT NULL,
  review_status text NOT NULL DEFAULT 'AUTO' CHECK(review_status IN ('AUTO','REVIEWED','OPERATOR_EDITED')),
  supersedes_display_metadata_id text REFERENCES memory_display_metadata(display_metadata_id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(memory_id,display_version)
);
CREATE INDEX IF NOT EXISTS idx_memory_display_current ON memory_display_metadata(tenant_id,memory_id,display_version DESC);
CREATE INDEX IF NOT EXISTS idx_memory_display_title ON memory_display_metadata(tenant_id,lower(human_title));

CREATE TABLE IF NOT EXISTS memory_operator_actions(
  action_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  memory_id text REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  scope_id text REFERENCES memory_scopes(scope_id) ON DELETE RESTRICT,
  action_type text NOT NULL CHECK(action_type IN (
    'KEEP_PERMANENT','ACTIVATE','ARCHIVE','PROTECT_HOLD','UNPROTECT',
    'DELETE_REQUESTED','DELETE_BLOCKED','DELETE_QUARANTINED','DELETE_UNDONE','PURGE_COMPLETED',
    'PROMOTE_SCOPE','MOVE_SCOPE','RENAME_DISPLAY_TITLE','EDIT_DISPLAY_SUMMARY','RENAME_SCOPE'
  )),
  actor_id text NOT NULL,
  reason text,
  before_state_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
  after_state_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
  result text NOT NULL,
  correlation_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_operator_actions_memory ON memory_operator_actions(tenant_id,memory_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_operator_actions_type ON memory_operator_actions(tenant_id,action_type,created_at DESC);

CREATE TABLE IF NOT EXISTS memory_delete_requests(
  delete_request_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  memory_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  requested_by text NOT NULL,
  requested_at timestamptz NOT NULL DEFAULT now(),
  state text NOT NULL CHECK(state IN (
    'REQUESTED','VALIDATING','BLOCKED_DEPENDENCY','BLOCKED_HOLD','QUARANTINED',
    'UNDONE','PURGE_ELIGIBLE','PURGED','FAILED'
  )),
  dependency_check_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
  hold_check_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
  before_state_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
  quarantine_until timestamptz,
  lifecycle_request_id text REFERENCES lifecycle_requests(request_id) ON DELETE RESTRICT,
  blocked_reason text,
  completed_at timestamptz,
  idempotency_key text NOT NULL,
  correlation_id text NOT NULL,
  UNIQUE(tenant_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_memory_delete_requests_memory ON memory_delete_requests(tenant_id,memory_id,requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_delete_requests_state ON memory_delete_requests(tenant_id,state,requested_at DESC);

CREATE TABLE IF NOT EXISTS memory_scope_promotions(
  promotion_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  source_memory_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  promoted_memory_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  from_scope text NOT NULL,
  from_scope_ref text,
  to_scope text NOT NULL,
  actor_id text NOT NULL,
  reason text NOT NULL,
  source_version_id text REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  evidence_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(tenant_id,source_memory_id,promoted_memory_id)
);
CREATE INDEX IF NOT EXISTS idx_memory_scope_promotions_source ON memory_scope_promotions(tenant_id,source_memory_id,created_at DESC);

CREATE TABLE IF NOT EXISTS integrity_manifests(
  manifest_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  scope_type text NOT NULL,
  scope_id text NOT NULL,
  range_start text,
  range_end text,
  root_hash text NOT NULL CHECK(root_hash ~ '^[0-9a-f]{64}$'),
  previous_manifest_hash text,
  manifest_hash text NOT NULL UNIQUE CHECK(manifest_hash ~ '^[0-9a-f]{64}$'),
  signature_algorithm text NOT NULL,
  signature_key_version integer NOT NULL CHECK(signature_key_version >= 1),
  public_key_sha256 text NOT NULL CHECK(public_key_sha256 ~ '^[0-9a-f]{64}$'),
  signature_b64 text NOT NULL,
  external_anchor_ref text NOT NULL,
  verification_state text NOT NULL CHECK(verification_state IN ('VERIFIED','FAILED','DEGRADED')),
  anchored_at timestamptz NOT NULL,
  metadata_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_integrity_manifests_scope ON integrity_manifests(tenant_id,scope_type,scope_id,created_at DESC);

-- M17 requires undo before purge. Cancellation never mutates canonical memory bytes.
ALTER TABLE lifecycle_requests DROP CONSTRAINT IF EXISTS lifecycle_requests_status_check;
ALTER TABLE lifecycle_requests ADD CONSTRAINT lifecycle_requests_status_check
  CHECK(status IN ('REQUESTED','QUARANTINED','APPROVED','PURGED','RECOVERED','FINALIZED','BLOCKED','CANCELLED'));

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'memory_scopes','memory_display_metadata','memory_operator_actions',
    'memory_delete_requests','memory_scope_promotions','integrity_manifests'
  ] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I',t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id))',t);
  END LOOP;
END $$;

-- Human metadata/actions/promotions/manifests are historical records; corrections append a new row.
DO $$
DECLARE t text; trg text;
BEGIN
  FOREACH t IN ARRAY ARRAY['memory_display_metadata','memory_operator_actions','memory_scope_promotions','integrity_manifests'] LOOP
    trg:=left('trg_'||t||'_append_only',63);
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I',trg,t);
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation()',trg,t);
  END LOOP;
END $$;

GRANT SELECT,INSERT,UPDATE ON memory_scopes TO memory_app;
GRANT SELECT,INSERT ON memory_display_metadata,memory_operator_actions,memory_scope_promotions,integrity_manifests TO memory_app;
GRANT SELECT,INSERT,UPDATE ON memory_delete_requests TO memory_app;
GRANT SELECT ON memory_scopes,memory_display_metadata,memory_operator_actions,memory_scope_promotions,memory_delete_requests,integrity_manifests TO memory_admin;

-- Backfill a structurally explicit global scope and project scopes from existing canonical memories.
INSERT INTO memory_scopes(scope_id,tenant_id,scope_type,display_name,status)
SELECT 'scope-global-'||substr(md5(tenant_id),1,24),tenant_id,'GLOBAL_USER','Memórias Gerais','ACTIVE'
FROM memory_items GROUP BY tenant_id
ON CONFLICT DO NOTHING;

INSERT INTO memory_scopes(scope_id,tenant_id,scope_type,parent_scope_id,project_id,display_name,status)
SELECT 'scope-project-'||substr(md5(m.tenant_id||':'||m.memory_scope_ref),1,24),m.tenant_id,'PROJECT',
       'scope-global-'||substr(md5(m.tenant_id),1,24),m.memory_scope_ref,
       'Projeto · '||regexp_replace(replace(replace(m.memory_scope_ref,'_',' '),'-',' '),'\s+',' ','g'),'ACTIVE'
FROM memory_items m
WHERE m.memory_scope='PROJECT' AND NULLIF(m.memory_scope_ref,'') IS NOT NULL
GROUP BY m.tenant_id,m.memory_scope_ref
ON CONFLICT DO NOTHING;

-- Every existing visible memory gets deterministic human metadata; later edits append versions.
INSERT INTO memory_display_metadata(
  display_metadata_id,tenant_id,memory_id,display_version,human_title,human_summary,source_context_summary,
  topic_tags_jsonb,source_kind,source_label,language,generated_by,review_status
)
SELECT 'dmeta-'||substr(md5(m.tenant_id||':'||m.item_id||':1'),1,28),m.tenant_id,m.item_id,1,
       left(COALESCE(NULLIF(btrim(m.memory_key),''),'Memória registrada'),300),
       left(COALESCE(NULLIF(btrim(m.content_text),''),'Conteúdo preservado na memória soberana.'),1200),
       left(COALESCE(NULLIF(btrim(m.provenance->>'source_context_summary'),''),NULLIF(btrim(m.provenance->>'context'),''),
                     'Origem: '||m.source||' · registrada em '||to_char(m.created_at,'YYYY-MM-DD HH24:MI TZ')),1200),
       to_jsonb(COALESCE(m.tags,ARRAY[]::text[])),COALESCE(NULLIF(m.category,''),'MEMORY'),m.source,'pt-BR','migration-0052','AUTO'
FROM memory_items m
WHERE NOT EXISTS(SELECT 1 FROM memory_display_metadata d WHERE d.memory_id=m.item_id)
ON CONFLICT DO NOTHING;

INSERT INTO schema_meta(key,value) VALUES
('schema_version','memory-0.30.0'),
('human_governance_contract_version','M17-1.0.0'),
('integrity_anchor_contract_version','M16-1.0.0'),
('gate_m16_status','PENDING'),
('gate_m17_status','PENDING')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();

-- Keep human scope registry and display metadata synchronized for all future canonical memories.
CREATE OR REPLACE FUNCTION memory_sync_human_scope_and_display() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  global_id text;
  project_ref text;
  project_scope_id text;
  mission_ref text;
  mission_scope_id text;
  session_ref text;
  project_name text;
  mission_name text;
  session_name text;
  next_display integer;
BEGIN
  global_id := 'scope-global-'||substr(md5(NEW.tenant_id),1,24);
  INSERT INTO memory_scopes(scope_id,tenant_id,scope_type,display_name,status)
  VALUES(global_id,NEW.tenant_id,'GLOBAL_USER','MemÃ³rias Gerais','ACTIVE')
  ON CONFLICT DO NOTHING;

  project_ref := NULLIF(COALESCE(NEW.project_id,CASE WHEN NEW.memory_scope='PROJECT' THEN NEW.memory_scope_ref END,''),'');
  IF project_ref IS NOT NULL THEN
    project_scope_id := 'scope-project-'||substr(md5(NEW.tenant_id||':'||project_ref),1,24);
    project_name := COALESCE(
      NULLIF(NEW.provenance->>'project_display_name',''),
      NULLIF(NEW.provenance#>>'{asserted_provenance,project_display_name}',''),
      NULLIF(NEW.provenance->>'project_name',''),
      regexp_replace(replace(replace(project_ref,'_',' '),'-',' '),'\s+',' ','g')
    );
    INSERT INTO memory_scopes(scope_id,tenant_id,scope_type,parent_scope_id,project_id,display_name,status)
    VALUES(project_scope_id,NEW.tenant_id,'PROJECT',global_id,project_ref,left(project_name,240),'ACTIVE')
    ON CONFLICT DO NOTHING;
  END IF;

  IF NEW.memory_scope='MISSION' AND NULLIF(NEW.memory_scope_ref,'') IS NOT NULL THEN
    mission_ref := NEW.memory_scope_ref;
    mission_scope_id := 'scope-mission-'||substr(md5(NEW.tenant_id||':'||mission_ref),1,24);
    mission_name := COALESCE(NULLIF(NEW.provenance->>'mission_display_name',''),NULLIF(NEW.provenance#>>'{asserted_provenance,mission_display_name}',''),'MissÃ£o Â· '||mission_ref);
    INSERT INTO memory_scopes(scope_id,tenant_id,scope_type,parent_scope_id,user_id,project_id,mission_id,display_name,status)
    VALUES(mission_scope_id,NEW.tenant_id,'MISSION',COALESCE(project_scope_id,global_id),NEW.owner_user_id,project_ref,mission_ref,left(mission_name,240),'ACTIVE')
    ON CONFLICT DO NOTHING;
  END IF;

  IF NEW.memory_scope='SESSION' AND NULLIF(NEW.memory_scope_ref,'') IS NOT NULL THEN
    session_ref := NEW.memory_scope_ref;
    mission_ref := COALESCE(NULLIF(NEW.provenance->>'mission_id',''),NULLIF(NEW.provenance#>>'{asserted_provenance,mission_id}',''));
    IF mission_ref IS NOT NULL THEN
      mission_scope_id := 'scope-mission-'||substr(md5(NEW.tenant_id||':'||mission_ref),1,24);
      mission_name := COALESCE(NULLIF(NEW.provenance->>'mission_display_name',''),NULLIF(NEW.provenance#>>'{asserted_provenance,mission_display_name}',''),'MissÃ£o Â· '||mission_ref);
      INSERT INTO memory_scopes(scope_id,tenant_id,scope_type,parent_scope_id,user_id,project_id,mission_id,display_name,status)
      VALUES(mission_scope_id,NEW.tenant_id,'MISSION',COALESCE(project_scope_id,global_id),NEW.owner_user_id,project_ref,mission_ref,left(mission_name,240),'ACTIVE')
      ON CONFLICT DO NOTHING;
    END IF;
    session_name := COALESCE(NULLIF(NEW.provenance->>'session_display_name',''),NULLIF(NEW.provenance#>>'{asserted_provenance,session_display_name}',''),'SessÃ£o Â· '||session_ref);
    INSERT INTO memory_scopes(scope_id,tenant_id,scope_type,parent_scope_id,user_id,project_id,mission_id,session_id,display_name,status)
    VALUES('scope-session-'||substr(md5(NEW.tenant_id||':'||session_ref),1,24),NEW.tenant_id,'SESSION',COALESCE(mission_scope_id,project_scope_id,global_id),NEW.owner_user_id,project_ref,mission_ref,session_ref,left(session_name,240),'ACTIVE')
    ON CONFLICT DO NOTHING;
  END IF;

  IF NOT EXISTS(SELECT 1 FROM memory_display_metadata d WHERE d.memory_id=NEW.item_id) THEN
    SELECT COALESCE(max(display_version),0)+1 INTO next_display FROM memory_display_metadata WHERE memory_id=NEW.item_id;
    INSERT INTO memory_display_metadata(
      display_metadata_id,tenant_id,memory_id,display_version,human_title,human_summary,source_context_summary,
      topic_tags_jsonb,source_kind,source_label,language,generated_by,review_status
    ) VALUES(
      'dmeta-'||substr(md5(NEW.tenant_id||':'||NEW.item_id||':'||next_display::text),1,28),NEW.tenant_id,NEW.item_id,next_display,
      left(COALESCE(NULLIF(btrim(NEW.memory_key),''),'MemÃ³ria registrada'),300),
      left(COALESCE(NULLIF(btrim(NEW.content_text),''),'ConteÃºdo preservado na memÃ³ria soberana.'),1200),
      left(COALESCE(NULLIF(btrim(NEW.provenance->>'source_context_summary'),''),NULLIF(btrim(NEW.provenance#>>'{asserted_provenance,source_context_summary}'),''),NULLIF(btrim(NEW.provenance->>'context'),''),'Origem: '||NEW.source),1200),
      to_jsonb(COALESCE(NEW.tags,ARRAY[]::text[])),COALESCE(NULLIF(NEW.category,''),'MEMORY'),NEW.source,'pt-BR','memory-sync-trigger','AUTO'
    );
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_memory_sync_human_scope_and_display ON memory_items;
CREATE TRIGGER trg_memory_sync_human_scope_and_display
AFTER INSERT OR UPDATE OF memory_scope,memory_scope_ref,project_id,memory_key,content_text,provenance,tags,source,category
ON memory_items FOR EACH ROW EXECUTE FUNCTION memory_sync_human_scope_and_display();

-- Backfill mission/session hierarchy with INSERT-only statements. Never fire memory UPDATE triggers.
INSERT INTO memory_scopes(scope_id,tenant_id,scope_type,parent_scope_id,user_id,project_id,mission_id,display_name,status)
SELECT 'scope-mission-'||substr(md5(m.tenant_id||':'||m.memory_scope_ref),1,24),m.tenant_id,'MISSION',
       COALESCE(
         CASE WHEN NULLIF(m.project_id,'') IS NOT NULL THEN 'scope-project-'||substr(md5(m.tenant_id||':'||m.project_id),1,24) END,
         'scope-global-'||substr(md5(m.tenant_id),1,24)
       ),m.owner_user_id,m.project_id,m.memory_scope_ref,
       left(COALESCE(NULLIF(m.provenance->>'mission_display_name',''),NULLIF(m.provenance#>>'{asserted_provenance,mission_display_name}',''),'Missao - '||m.memory_scope_ref),240),'ACTIVE'
FROM memory_items m
WHERE m.memory_scope='MISSION' AND NULLIF(m.memory_scope_ref,'') IS NOT NULL
GROUP BY m.tenant_id,m.owner_user_id,m.project_id,m.memory_scope_ref,m.provenance
ON CONFLICT DO NOTHING;

INSERT INTO memory_scopes(scope_id,tenant_id,scope_type,parent_scope_id,user_id,project_id,mission_id,session_id,display_name,status)
SELECT 'scope-session-'||substr(md5(m.tenant_id||':'||m.memory_scope_ref),1,24),m.tenant_id,'SESSION',
       COALESCE(
         CASE WHEN NULLIF(COALESCE(m.provenance->>'mission_id',m.provenance#>>'{asserted_provenance,mission_id}'),'') IS NOT NULL
              THEN 'scope-mission-'||substr(md5(m.tenant_id||':'||COALESCE(m.provenance->>'mission_id',m.provenance#>>'{asserted_provenance,mission_id}')),1,24) END,
         CASE WHEN NULLIF(m.project_id,'') IS NOT NULL THEN 'scope-project-'||substr(md5(m.tenant_id||':'||m.project_id),1,24) END,
         'scope-global-'||substr(md5(m.tenant_id),1,24)
       ),m.owner_user_id,m.project_id,
       COALESCE(m.provenance->>'mission_id',m.provenance#>>'{asserted_provenance,mission_id}'),m.memory_scope_ref,
       left(COALESCE(NULLIF(m.provenance->>'session_display_name',''),NULLIF(m.provenance#>>'{asserted_provenance,session_display_name}',''),'Sessao - '||m.memory_scope_ref),240),'ACTIVE'
FROM memory_items m
WHERE m.memory_scope='SESSION' AND NULLIF(m.memory_scope_ref,'') IS NOT NULL
GROUP BY m.tenant_id,m.owner_user_id,m.project_id,m.memory_scope_ref,m.provenance
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS integrity_anchor_events(
  event_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  manifest_id text,
  event_type text NOT NULL CHECK(event_type IN ('ANCHOR_CREATED','ANCHOR_DEGRADED','VERIFY_PASS','VERIFY_FAIL','KEY_ROTATED')),
  status text NOT NULL CHECK(status IN ('PASS','FAIL','DEGRADED')),
  detail_jsonb jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(detail_jsonb)='object'),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_integrity_anchor_events_created ON integrity_anchor_events(tenant_id,created_at DESC);
ALTER TABLE integrity_anchor_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE integrity_anchor_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON integrity_anchor_events;
CREATE POLICY tenant_isolation ON integrity_anchor_events
  USING(memory_rls_visible(tenant_id)) WITH CHECK(memory_rls_visible(tenant_id));
DROP TRIGGER IF EXISTS trg_integrity_anchor_events_append_only ON integrity_anchor_events;
CREATE TRIGGER trg_integrity_anchor_events_append_only
BEFORE UPDATE OR DELETE ON integrity_anchor_events FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();
GRANT SELECT,INSERT ON integrity_anchor_events TO memory_app;
GRANT SELECT ON integrity_anchor_events TO memory_admin;
