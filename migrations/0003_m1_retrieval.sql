CREATE TABLE IF NOT EXISTS memory_embeddings(
  item_id text PRIMARY KEY REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  model_id text NOT NULL,
  dimensions integer NOT NULL CHECK(dimensions > 0),
  embedding double precision[],
  content_sha256 text NOT NULL,
  status text NOT NULL CHECK(status IN ('PENDING','READY','FAILED')) DEFAULT 'PENDING',
  error_type text,
  error_message text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK(status <> 'READY' OR (embedding IS NOT NULL AND cardinality(embedding)=dimensions))
);
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_model_status ON memory_embeddings(model_id,status);

ALTER TABLE retrieval_traces ADD COLUMN IF NOT EXISTS state_json jsonb;
ALTER TABLE retrieval_traces ADD COLUMN IF NOT EXISTS retrieval_modes text[] NOT NULL DEFAULT '{}';

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.3.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
