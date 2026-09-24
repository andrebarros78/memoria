CREATE TABLE IF NOT EXISTS conversation_ingestion_events(
  event_id text PRIMARY KEY,
  tenant_id text NOT NULL,
  provider text NOT NULL,
  external_session_ref text NOT NULL,
  canonical_external_ref text NOT NULL,
  external_project_ref text,
  message_id text NOT NULL,
  role text NOT NULL,
  ordinal integer NOT NULL CHECK(ordinal >= 0),
  content_text text NOT NULL,
  content_sha256 text NOT NULL,
  objective text NOT NULL,
  project_id text,
  capture_source text NOT NULL,
  status text NOT NULL CHECK(status IN ('PENDING','PROCESSING','PROCESSED','FAILED','DEAD_LETTER')) DEFAULT 'PENDING',
  attempt_count integer NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error text,
  memory_id text,
  session_id text,
  checkpoint_id text,
  context_pack_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  processed_at timestamptz,
  UNIQUE(tenant_id, provider, canonical_external_ref, message_id)
);

CREATE INDEX IF NOT EXISTS idx_conversation_ingestion_status
  ON conversation_ingestion_events(tenant_id,status,next_attempt_at,created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_ingestion_conversation
  ON conversation_ingestion_events(tenant_id,provider,canonical_external_ref,ordinal,created_at);

DROP TRIGGER IF EXISTS trg_set_tenant ON conversation_ingestion_events;
CREATE TRIGGER trg_set_tenant
BEFORE INSERT ON conversation_ingestion_events
FOR EACH ROW EXECUTE FUNCTION memory_set_tenant_from_context();

ALTER TABLE conversation_ingestion_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_ingestion_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON conversation_ingestion_events;
CREATE POLICY tenant_isolation ON conversation_ingestion_events
USING (memory_rls_visible(tenant_id))
WITH CHECK (memory_rls_visible(tenant_id));

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.10.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
