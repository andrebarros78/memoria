from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _sql(name: str) -> str:
    return (ROOT / "migrations" / name).read_text(encoding="utf-8")


def test_0057_association_migration_is_shadow_rls_append_only_and_least_privilege():
    sql = _sql("0057_cognitive_associative_memory.sql")
    assert "CREATE TABLE IF NOT EXISTS memory_association_traversals" in sql
    assert "CREATE TABLE IF NOT EXISTS memory_association_candidates" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "memory_record_association_traversal_shadow" in sql
    assert "SECURITY DEFINER" in sql
    assert "runtime tenant context is required for association traversal" in sql
    assert "association candidate outside traversal scope" in sql
    assert "forbid_append_only_mutation" in sql
    assert "REVOKE INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER" in sql
    assert "GRANT SELECT ON memory_association_traversals,memory_association_candidates TO memory_app" in sql
    assert "cognitive_association_version','ASP-1.0.0'" in sql


def test_0057_contains_all_executive_association_relation_types():
    sql = _sql("0057_cognitive_associative_memory.sql")
    for relation in (
        "SEMANTIC_SIMILARITY",
        "TEMPORAL_PROXIMITY",
        "CAUSAL_RELATION",
        "SHARED_ENTITY",
        "SHARED_PERSON",
        "SHARED_OBJECTIVE",
        "SHARED_CONTEXT",
        "SHARED_OUTCOME",
        "CO_OCCURRENCE",
        "PROCEDURAL_DEPENDENCY",
        "DECISION_DEPENDENCY",
        "CONTRADICTION",
        "SUPPORT",
    ):
        assert relation in sql


def test_phase3_migration_number_follows_phase2_head_without_reuse():
    names = sorted(path.name for path in (ROOT / "migrations").glob("*.sql"))
    assert "0056_cognitive_salience.sql" in names
    assert "0057_cognitive_associative_memory.sql" in names
    assert names.index("0056_cognitive_salience.sql") < names.index("0057_cognitive_associative_memory.sql")
