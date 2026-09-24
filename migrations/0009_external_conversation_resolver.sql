ALTER TABLE external_session_bindings
  ADD COLUMN IF NOT EXISTS canonical_external_ref text,
  ADD COLUMN IF NOT EXISTS external_project_ref text;

UPDATE external_session_bindings
SET canonical_external_ref = CASE
  WHEN lower(provider) IN ('chatgpt','chatgpt_web','openai_chatgpt') AND external_session_ref ~ '/c/[A-Za-z0-9-]+$'
    THEN regexp_replace(external_session_ref, '^.*/c/', '')
  ELSE external_session_ref
END
WHERE canonical_external_ref IS NULL OR canonical_external_ref='';

UPDATE external_session_bindings
SET external_project_ref = substring(external_session_ref from '(g/g-p-[^/]+)/c/')
WHERE external_project_ref IS NULL AND lower(provider) IN ('chatgpt','chatgpt_web','openai_chatgpt');

ALTER TABLE external_session_bindings ALTER COLUMN canonical_external_ref SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_external_session_ref
ON external_session_bindings(external_session_ref);

CREATE INDEX IF NOT EXISTS idx_external_session_resolver
ON external_session_bindings(lower(provider),canonical_external_ref,status,created_at DESC);

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.9.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
