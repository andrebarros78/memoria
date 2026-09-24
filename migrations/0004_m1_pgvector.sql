DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_extension WHERE extname='vector' AND extversion='0.8.6'
  ) THEN
    RAISE EXCEPTION 'pgvector 0.8.6 must be installed and enabled before migration 0004';
  END IF;
END;
$$;

ALTER TABLE memory_embeddings
  ADD COLUMN IF NOT EXISTS embedding_vector vector(384);

UPDATE memory_embeddings
SET embedding_vector = ('[' || array_to_string(embedding, ',') || ']')::vector
WHERE status='READY'
  AND model_id='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
  AND dimensions=384
  AND embedding IS NOT NULL
  AND embedding_vector IS NULL;

ALTER TABLE memory_embeddings
  DROP CONSTRAINT IF EXISTS chk_memory_embeddings_pgvector_ready;
ALTER TABLE memory_embeddings
  ADD CONSTRAINT chk_memory_embeddings_pgvector_ready
  CHECK(
    status <> 'READY'
    OR model_id <> 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
    OR dimensions <> 384
    OR embedding_vector IS NOT NULL
  ) NOT VALID;
ALTER TABLE memory_embeddings
  VALIDATE CONSTRAINT chk_memory_embeddings_pgvector_ready;

CREATE INDEX IF NOT EXISTS idx_memory_embeddings_hnsw_cosine
ON memory_embeddings
USING hnsw (embedding_vector vector_cosine_ops)
WHERE status='READY' AND embedding_vector IS NOT NULL;

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.4.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
