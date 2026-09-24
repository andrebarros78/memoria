from __future__ import annotations

from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MIGRATION=ROOT/"migrations/0042_runtime_least_privilege.sql"


def test_0042_revokes_historical_broad_runtime_grants():
    text=MIGRATION.read_text(encoding="utf-8")
    assert "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM memory_app" in text
    assert "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM memory_app" in text
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE memory_admin" in text
    assert "REVOKE ALL PRIVILEGES ON TABLES FROM memory_app" in text


def test_schema_and_audit_tables_are_not_runtime_mutable():
    text=MIGRATION.read_text(encoding="utf-8")
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE schema_migrations FROM memory_app" in text
    assert "REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE audit_events FROM memory_app" in text
    assert "REVOKE ALL PRIVILEGES ON TABLE legacy_security_audit, provider_invocations FROM memory_app" in text


def test_runtime_schema_meta_gate_is_allowlisted_and_security_definer():
    text=MIGRATION.read_text(encoding="utf-8")
    assert "SECURITY DEFINER" in text
    assert "memory_set_runtime_gate" in text
    for key in ("restore_erasure_replay_status","p18_status","gate_m12_status"):
        assert key in text
    for forbidden in ("schema_version","lifecycle_direct_purge_enabled"):
        # schema_version must not be part of the function allowlist. It may only appear in comments if ever added.
        function=text.split("CREATE OR REPLACE FUNCTION memory_set_runtime_gate",1)[1].split("$$;",1)[0]
        assert forbidden not in function


def test_runtime_managers_never_write_schema_meta_directly():
    for rel in ("src/memory_permanent/erasure_manager.py","src/memory_permanent/lifecycle_manager.py"):
        text=(ROOT/rel).read_text(encoding="utf-8")
        assert "INSERT INTO schema_meta" not in text
        assert "memory_set_runtime_gate" in text


def test_delete_privilege_is_only_for_embedding_cleanup():
    text=MIGRATION.read_text(encoding="utf-8")
    grants=[line.strip() for line in text.splitlines() if line.strip().startswith("GRANT DELETE ON TABLE") ]
    assert grants == ["GRANT DELETE ON TABLE memory_embeddings TO memory_app;"]
