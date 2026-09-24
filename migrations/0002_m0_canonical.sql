CREATE TABLE IF NOT EXISTS memory_versions(
  version_id text PRIMARY KEY,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  version_no integer NOT NULL CHECK(version_no > 0),
  content_json jsonb NOT NULL,
  content_text text NOT NULL,
  provenance jsonb NOT NULL,
  confidence double precision NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  source text NOT NULL,
  source_version text,
  tags text[] NOT NULL DEFAULT '{}',
  content_sha256 text NOT NULL,
  previous_version_id text,
  request_sha256 text NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(item_id, version_no)
);
CREATE INDEX IF NOT EXISTS idx_memory_versions_item ON memory_versions(item_id,version_no DESC);

CREATE TABLE IF NOT EXISTS memory_events(
  event_seq bigserial PRIMARY KEY,
  event_id text NOT NULL UNIQUE,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  version_id text REFERENCES memory_versions(version_id) ON DELETE RESTRICT,
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  request_sha256 text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_memory_events_item ON memory_events(item_id,event_seq);

CREATE TABLE IF NOT EXISTS idempotency_records(
  operation text NOT NULL,
  idempotency_key text NOT NULL,
  request_sha256 text NOT NULL,
  response_json jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(operation,idempotency_key)
);

INSERT INTO memory_versions(
  version_id,item_id,version_no,content_json,content_text,provenance,confidence,source,source_version,tags,
  content_sha256,previous_version_id,request_sha256,created_by,created_at
)
SELECT
  'ver-backfill-' || md5(m.item_id),m.item_id,1,m.content_json,m.content_text,m.provenance,m.confidence,m.source,m.source_version,m.tags,
  m.content_sha256,NULL,m.content_sha256,'MIGRATION_0002',m.created_at
FROM memory_items m
WHERE NOT EXISTS (SELECT 1 FROM memory_versions v WHERE v.item_id=m.item_id);

INSERT INTO memory_events(event_id,item_id,version_id,event_type,payload,request_sha256,created_at)
SELECT
  'evt-backfill-' || md5(m.item_id),m.item_id,'ver-backfill-' || md5(m.item_id),'MEMORY_BACKFILLED',
  jsonb_build_object('content_sha256',m.content_sha256,'migration','0002_m0_canonical'),m.content_sha256,m.created_at
FROM memory_items m
WHERE NOT EXISTS (SELECT 1 FROM memory_events e WHERE e.item_id=m.item_id);

CREATE OR REPLACE FUNCTION forbid_append_only_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'append-only table % forbids %', TG_TABLE_NAME, TG_OP USING ERRCODE='55000';
END;
$$;

DROP TRIGGER IF EXISTS trg_memory_versions_append_only ON memory_versions;
CREATE TRIGGER trg_memory_versions_append_only BEFORE UPDATE OR DELETE ON memory_versions
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

DROP TRIGGER IF EXISTS trg_memory_events_append_only ON memory_events;
CREATE TRIGGER trg_memory_events_append_only BEFORE UPDATE OR DELETE ON memory_events
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;
CREATE TRIGGER trg_audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation();

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.2.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
