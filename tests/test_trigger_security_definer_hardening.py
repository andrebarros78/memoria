from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
M=(ROOT/"migrations/0044_trigger_security_definer_hardening.sql").read_text(encoding="utf-8")

def test_internal_trigger_functions_are_definer_scoped():
    functions=("enqueue_memory_event_outbox","memory_invalidate_derived_on_new_version","memory_stale_knowledge_relations_on_new_version","memory_record_artifact_state_change","memory_record_knowledge_relation_insert","memory_record_knowledge_relation_status")
    for fn in functions:
        assert f"ALTER FUNCTION {fn}() SECURITY DEFINER" in M
        assert f"ALTER FUNCTION {fn}() SET search_path=pg_catalog,public,pg_temp" in M
        assert f"REVOKE ALL ON FUNCTION {fn}() FROM PUBLIC" in M

def test_temporary_indirect_table_grants_are_removed():
    for marker in ("REVOKE ALL PRIVILEGES ON TABLE memory_outbox FROM memory_app","REVOKE UPDATE ON TABLE memory_derived_artifacts FROM memory_app","REVOKE UPDATE ON TABLE memory_knowledge_relations FROM memory_app","REVOKE INSERT ON TABLE memory_artifact_state_events FROM memory_app","REVOKE INSERT ON TABLE memory_knowledge_relation_events FROM memory_app"):
        assert marker in M
    assert "GRANT " not in M