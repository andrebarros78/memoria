-- V5.3 AI adapter runtime grants.
GRANT SELECT, INSERT ON TABLE ai_integration_suggestions TO memory_app;
GRANT SELECT, INSERT ON TABLE ai_integration_decisions TO memory_app;
INSERT INTO schema_meta(key,value) VALUES('ai_integration_runtime_privilege_version','AIRP-1.0.0') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
