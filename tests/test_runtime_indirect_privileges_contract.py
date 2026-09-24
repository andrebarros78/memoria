from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
M=(ROOT/"migrations/0043_runtime_indirect_privileges.sql").read_text(encoding="utf-8")

def test_trigger_dependencies_are_minimally_granted():
    for marker in (
        "GRANT INSERT ON TABLE memory_outbox TO memory_app",
        "GRANT UPDATE ON TABLE memory_derived_artifacts TO memory_app",
        "GRANT UPDATE ON TABLE memory_knowledge_relations TO memory_app",
        "GRANT INSERT ON TABLE memory_artifact_state_events TO memory_app",
        "GRANT INSERT ON TABLE memory_knowledge_relation_events TO memory_app",
    ): assert marker in M
    assert "GRANT DELETE" not in M

def test_m12_projection_uses_security_definer_without_schema_meta_grant():
    assert "ALTER FUNCTION memory_sync_ui_governance_from_m12() SECURITY DEFINER" in M
    assert "SET search_path=pg_catalog,public,pg_temp" in M
    assert "schema_meta TO memory_app" not in M