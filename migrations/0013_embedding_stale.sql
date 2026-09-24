ALTER TABLE memory_embeddings DROP CONSTRAINT IF EXISTS memory_embeddings_status_check;
ALTER TABLE memory_embeddings ADD CONSTRAINT memory_embeddings_status_check
  CHECK(status IN ('PENDING','READY','FAILED','STALE'));

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.11.1')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
