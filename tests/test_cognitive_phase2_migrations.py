from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sql(name: str) -> str:
    return (ROOT / "migrations" / name).read_text(encoding="utf-8")


def test_0055_activation_migration_is_rls_shadow_and_least_privilege():
    sql = _sql("0055_cognitive_activation.sql")
    for table in (
        "memory_activation_state",
        "memory_activation_events",
        "memory_priming_edges",
        "memory_interference_events",
    ):
        assert table in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "memory_record_activation_shadow" in sql
    assert "memory_record_priming_shadow" in sql
    assert "SECURITY DEFINER" in sql
    assert "memory_app may not use system tenant" in sql
    assert "cross-tenant priming is forbidden" in sql
    assert "REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER" in sql
    assert "forbid_append_only_mutation" in sql
    assert "gate_c1_status','PENDING'" in sql


def test_0056_salience_migration_is_append_only_and_no_consumer_write():
    sql = _sql("0056_cognitive_salience.sql")
    assert "CREATE TABLE IF NOT EXISTS memory_salience" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "memory_record_salience_shadow" in sql
    assert "SECURITY DEFINER" in sql
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER ON memory_salience FROM memory_app" in sql
    assert "mode text NOT NULL DEFAULT 'SHADOW' CHECK(mode='SHADOW')" in sql
    assert "gate_c2_status','PENDING'" in sql


def test_phase2_migration_numbers_follow_real_head_without_reuse():
    names = sorted(path.name for path in (ROOT / "migrations").glob("*.sql"))
    assert "0054_embedding_worker_role_login_normalization.sql" in names
    assert "0055_cognitive_activation.sql" in names
    assert "0056_cognitive_salience.sql" in names
    assert names.index("0054_embedding_worker_role_login_normalization.sql") < names.index("0055_cognitive_activation.sql")
    assert names.index("0055_cognitive_activation.sql") < names.index("0056_cognitive_salience.sql")
