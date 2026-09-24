from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "0047_derived_artifact_runtime_boundary.sql"
DEFINER_PRIVILEGES = ROOT / "migrations" / "0048_derived_artifact_definer_privileges.sql"
NO_DIRECT_WRITE = ROOT / "migrations" / "0049_derived_artifact_no_direct_write.sql"
STORE = ROOT / "src" / "memory_permanent" / "store.py"


def test_runtime_boundary_uses_security_definer_and_keeps_direct_update_revoked() -> None:
    text = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION memory_upsert_derived_artifact" in text
    assert "SECURITY DEFINER" in text
    assert "SET search_path=pg_catalog,public,pg_temp" in text
    assert "OWNER TO memory_admin" in text
    assert "GRANT EXECUTE ON FUNCTION memory_upsert_derived_artifact" in text
    assert "REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE memory_derived_artifacts FROM memory_app" in text
    assert "GRANT UPDATE ON TABLE memory_derived_artifacts TO memory_app" not in text


def test_runtime_boundary_derives_tenant_from_source_versions() -> None:
    text = MIGRATION.read_text(encoding="utf-8")
    assert "FROM public.memory_versions AS v" in text
    assert "count(DISTINCT v.tenant_id)" in text
    assert "cross-tenant derived artifact sources are forbidden" in text
    assert "derived artifact tenant mismatch" in text
    assert "memory_app may not use system tenant" in text


def test_security_definer_owner_gets_only_required_table_rights() -> None:
    text = DEFINER_PRIVILEGES.read_text(encoding="utf-8")
    assert "GRANT SELECT ON TABLE memory_versions TO memory_admin" in text
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE memory_derived_artifacts TO memory_admin" in text
    assert "GRANT UPDATE ON TABLE memory_derived_artifacts TO memory_app" not in text


def test_runtime_has_no_direct_write_to_derived_artifact_table() -> None:
    text = NO_DIRECT_WRITE.read_text(encoding="utf-8")
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER" in text
    assert "ON TABLE memory_derived_artifacts FROM memory_app" in text
    assert "GRANT SELECT ON TABLE memory_derived_artifacts TO memory_app" in text
    assert "GRANT INSERT" not in text
    assert "GRANT UPDATE" not in text


def test_store_routes_derived_upsert_through_narrow_function() -> None:
    text = STORE.read_text(encoding="utf-8")
    helper_start = text.index("    def _register_derived_artifact_in_conn(")
    helper_end = text.index("    def list_derived_artifacts(", helper_start)
    helper = text[helper_start:helper_end]
    assert "SELECT memory_upsert_derived_artifact(" in helper
    assert "source_version_ids" in helper
    assert "INSERT INTO memory_derived_artifacts" not in helper
    assert "memory_artifact_dependencies" in helper
