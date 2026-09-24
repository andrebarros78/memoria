-- Reconcile runtime privileges for objects created by administrative migrations.
GRANT USAGE ON SCHEMA public TO memory_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO memory_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO memory_app;

ALTER DEFAULT PRIVILEGES FOR ROLE memory_admin IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO memory_app;
ALTER DEFAULT PRIVILEGES FOR ROLE memory_admin IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO memory_app;

INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.10.1')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
