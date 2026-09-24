-- V5.2 trigger boundary hardening discovered by live canary.
-- Internal trigger projections run with tightly scoped definer authority instead
-- of expanding memory_app direct table privileges.

ALTER FUNCTION enqueue_memory_event_outbox() SECURITY DEFINER;
ALTER FUNCTION enqueue_memory_event_outbox() SET search_path=pg_catalog,public,pg_temp;
REVOKE ALL ON FUNCTION enqueue_memory_event_outbox() FROM PUBLIC;

ALTER FUNCTION memory_invalidate_derived_on_new_version() SECURITY DEFINER;
ALTER FUNCTION memory_invalidate_derived_on_new_version() SET search_path=pg_catalog,public,pg_temp;
REVOKE ALL ON FUNCTION memory_invalidate_derived_on_new_version() FROM PUBLIC;

ALTER FUNCTION memory_stale_knowledge_relations_on_new_version() SECURITY DEFINER;
ALTER FUNCTION memory_stale_knowledge_relations_on_new_version() SET search_path=pg_catalog,public,pg_temp;
REVOKE ALL ON FUNCTION memory_stale_knowledge_relations_on_new_version() FROM PUBLIC;

ALTER FUNCTION memory_record_artifact_state_change() SECURITY DEFINER;
ALTER FUNCTION memory_record_artifact_state_change() SET search_path=pg_catalog,public,pg_temp;
REVOKE ALL ON FUNCTION memory_record_artifact_state_change() FROM PUBLIC;

ALTER FUNCTION memory_record_knowledge_relation_insert() SECURITY DEFINER;
ALTER FUNCTION memory_record_knowledge_relation_insert() SET search_path=pg_catalog,public,pg_temp;
REVOKE ALL ON FUNCTION memory_record_knowledge_relation_insert() FROM PUBLIC;

ALTER FUNCTION memory_record_knowledge_relation_status() SECURITY DEFINER;
ALTER FUNCTION memory_record_knowledge_relation_status() SET search_path=pg_catalog,public,pg_temp;
REVOKE ALL ON FUNCTION memory_record_knowledge_relation_status() FROM PUBLIC;

-- Remove the temporary direct grants introduced by 0043 now that trigger
-- execution owns the required internal authority.
REVOKE ALL PRIVILEGES ON TABLE memory_outbox FROM memory_app;
REVOKE UPDATE ON TABLE memory_derived_artifacts FROM memory_app;
REVOKE UPDATE ON TABLE memory_knowledge_relations FROM memory_app;
REVOKE INSERT ON TABLE memory_artifact_state_events FROM memory_app;
REVOKE INSERT ON TABLE memory_knowledge_relation_events FROM memory_app;

INSERT INTO schema_meta(key,value) VALUES('trigger_security_definer_version','TSD-1.0.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now();
