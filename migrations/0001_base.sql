CREATE TABLE IF NOT EXISTS schema_meta(
  key text PRIMARY KEY,
  value text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.1.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=now();

CREATE TABLE IF NOT EXISTS memory_items(
  item_id text PRIMARY KEY,
  namespace text NOT NULL,
  memory_key text NOT NULL,
  category text NOT NULL DEFAULT 'FACT',
  content_json jsonb NOT NULL,
  content_text text NOT NULL,
  provenance jsonb NOT NULL,
  confidence double precision NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  source text NOT NULL,
  source_version text,
  tags text[] NOT NULL DEFAULT '{}',
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_until timestamptz,
  supersedes_id text,
  content_sha256 text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  retrieval_count bigint NOT NULL DEFAULT 0,
  application_count bigint NOT NULL DEFAULT 0,
  success_count bigint NOT NULL DEFAULT 0,
  failure_count bigint NOT NULL DEFAULT 0,
  search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple',coalesce(content_text,''))) STORED
);
CREATE INDEX IF NOT EXISTS idx_memory_key_ns ON memory_items(memory_key,namespace,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_fts ON memory_items USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_memory_tags ON memory_items USING GIN(tags);

CREATE TABLE IF NOT EXISTS memory_operator_state(
  item_id text PRIMARY KEY REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  operator_class text NOT NULL CHECK(operator_class IN ('PERMANENTE','ATIVA','ARQUIVADA','DESCARTÁVEL','PROTEGIDA')),
  lifecycle_state text NOT NULL CHECK(lifecycle_state IN ('HOT','WARM','COLD','DELETE_ELIGIBLE','QUARANTINED','PURGED')),
  hold_type text,
  changed_by text NOT NULL,
  changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS retention_holds(
  hold_id text PRIMARY KEY,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  hold_type text NOT NULL,
  reason text NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  released_at timestamptz,
  status text NOT NULL CHECK(status IN ('ACTIVE','RELEASED')) DEFAULT 'ACTIVE'
);
CREATE INDEX IF NOT EXISTS idx_retention_holds_item ON retention_holds(item_id,status);

CREATE TABLE IF NOT EXISTS retrieval_traces(
  trace_id text PRIMARY KEY,
  query_text text NOT NULL,
  namespaces text[] NOT NULL,
  candidates jsonb NOT NULL,
  selected jsonb NOT NULL,
  conflicts jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS checkpoints(
  checkpoint_id text PRIMARY KEY,
  namespace text NOT NULL,
  mission_id text NOT NULL,
  step_index integer NOT NULL,
  state_json jsonb NOT NULL,
  state_sha256 text NOT NULL,
  created_at timestamptz NOT NULL,
  migration_source text
);
CREATE INDEX IF NOT EXISTS idx_memory_checkpoints_mission ON checkpoints(mission_id,step_index);

CREATE TABLE IF NOT EXISTS legacy_security_audit(
  legacy_seq bigint PRIMARY KEY,
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  previous_hash text NOT NULL,
  event_hash text NOT NULL,
  created_at timestamptz NOT NULL,
  migration_source text NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events(
  seq bigserial PRIMARY KEY,
  event_type text NOT NULL,
  target_id text,
  payload jsonb NOT NULL,
  previous_hash text NOT NULL,
  event_hash text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL
);
