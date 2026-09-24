from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_experience_graph_edge_validation_fix_is_unambiguous() -> None:
    sql = (ROOT / "migrations" / "0022_fix_experience_graph_edge_validation.sql").read_text(encoding="utf-8")
    assert "r.source_type=v_source_type" in sql
    assert "r.target_type=v_target_type" in sql
    assert "r.source_type=source_type" not in sql
    assert "r.target_type=target_type" not in sql
    assert "memory-0.16.1" in sql