-- V5.2 runtime least-privilege: indirect trigger dependencies discovered by live canary.
-- Keep 0042 immutable; add only the minimum privileges/functions required by
-- trigger-driven writes exercised by canonical runtime mutations.

-- memory_events AFTER INSERT -> enqueue_memory_event_outbox()
GRANT INSERT ON TABLE memory_outbox TO memory_app;

-- memory_versions AFTER INSERT on revision -> derived/knowledge invalidation.
GRANT UPDATE ON TABLE memory_derived_artifacts TO memory_app;
GRANT UPDATE ON TABLE memory_knowledge_relations TO memory_app;

-- Those state transitions emit append-only event rows from trigger functions.
GRANT INSERT ON TABLE memory_artifact_state_events TO memory_app;
GRANT INSERT ON TABLE memory_knowledge_relation_events TO memory_app;

-- M12 UI synchronization is a fixed-key internal projection. It must not force
-- direct schema_meta write privilege back onto memory_app.
ALTER FUNCTION memory_sync_ui_governance_from_m12() SECURITY DEFINER;
ALTER FUNCTION memory_sync_ui_governance_from_m12() SET search_path=pg_catalog,public,pg_temp;
REVOKE ALL ON FUNCTION memory_sync_ui_governance_from_m12() FROM PUBLIC;

INSERT INTO schema_meta(key,value) VALUES('runtime_indirect_privilege_version','RIP-1.0.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
