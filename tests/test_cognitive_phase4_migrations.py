from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sql(name: str) -> str:
    return (ROOT / "migrations" / name).read_text(encoding="utf-8")


def test_0058_follows_real_head_and_declares_f04_control_state():
    names = sorted(path.name for path in (ROOT / "migrations").glob("*.sql"))
    assert "0057_cognitive_associative_memory.sql" in names
    assert "0058_cognitive_offline_consolidation.sql" in names
    assert names.index("0057_cognitive_associative_memory.sql") < names.index(
        "0058_cognitive_offline_consolidation.sql"
    )
    sql = _sql("0058_cognitive_offline_consolidation.sql")
    for table in (
        "cognitive_consolidation_runs",
        "cognitive_consolidation_checkpoints",
        "cognitive_consolidation_candidates",
        "cognitive_consolidation_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
        assert table in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "gate_c4_status','PENDING'" in sql


def test_0058_requires_fenced_lease_and_security_definer_boundary():
    sql = _sql("0058_cognitive_offline_consolidation.sql")
    assert "memory_consolidation_assert_lease" in sql
    assert "agent_leases" in sql
    assert "fencing_token" in sql
    assert "expires_at>now()" in sql
    assert "SECURITY DEFINER" in sql
    assert "dedicated tenant/agent context required for consolidation" in sql
    assert "stale, expired or foreign consolidation lease" in sql
    assert "REVOKE ALL ON FUNCTION memory_start_consolidation_shadow" in sql
    assert "REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER" in sql


def test_0058_checkpoints_candidates_and_events_are_append_only():
    sql = _sql("0058_cognitive_offline_consolidation.sql")
    for table in (
        "cognitive_consolidation_checkpoints",
        "cognitive_consolidation_candidates",
        "cognitive_consolidation_events",
    ):
        assert table in sql
    assert "forbid_append_only_mutation()" in sql
    assert "VALIDATED_SHADOW" in sql
    assert "RECORD_PROVENANCE" in sql
    assert "memory_resume_consolidation_shadow" in sql
    assert "recovered_from_interrupt" in sql
