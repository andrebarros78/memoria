-- V5.3 correction: least-privilege rights for the SECURITY DEFINER owner.
-- memory_admin is non-superuser and cannot bypass RLS. Grant only the table
-- capabilities required by memory_upsert_derived_artifact(). memory_app remains
-- denied direct UPDATE on memory_derived_artifacts.

GRANT SELECT ON TABLE memory_versions TO memory_admin;
GRANT SELECT, INSERT, UPDATE ON TABLE memory_derived_artifacts TO memory_admin;

REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE memory_derived_artifacts FROM memory_app;

INSERT INTO schema_meta(key,value) VALUES('derived_artifact_definer_privileges_version','DADP-1.0.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
