from datetime import UTC, datetime

from memory_permanent.report import render_operational_report


def test_report_contains_governance_and_learning_metrics():
    summary = {
        "health": "OK",
        "memories_total": 10,
        "learning_items": 3,
        "operator_classes": {"PERMANENTE": 2, "ATIVA": 4, "ARQUIVADA": 1, "DESCARTÁVEL": 2, "PROTEGIDA": 1},
        "retrievals": 8,
        "applications": 4,
        "successes": 3,
        "failures": 1,
        "reuse_success_rate": 75.0,
        "conflicts": 0,
        "audit_events": 12,
        "purge_direct_enabled": False,
    }
    body = render_operational_report(summary, generated_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC))
    assert "Memórias totais: 10" in body
    assert "Descartáveis: 2" in body
    assert "75.0" in body
    assert "DELETE_ELIGIBLE" in body
    assert "Purge exige" in body
