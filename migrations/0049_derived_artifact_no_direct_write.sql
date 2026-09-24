-- V5.3 defense-in-depth: all runtime writes to memory_derived_artifacts must
-- traverse memory_upsert_derived_artifact(). The runtime role remains read-only
-- on the table itself; SECURITY DEFINER performs the constrained mutation.

REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
ON TABLE memory_derived_artifacts FROM memory_app;
GRANT SELECT ON TABLE memory_derived_artifacts TO memory_app;

INSERT INTO schema_meta(key,value) VALUES('derived_artifact_no_direct_write_version','DANDW-1.0.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
