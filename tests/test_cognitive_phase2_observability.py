from __future__ import annotations

from memory_permanent.api import app, get_cognitive_shadow_observer
from memory_permanent.cognitive_activation import CognitiveShadowObserver
from memory_permanent.cognitive_observability import (
    cognitive_observability_spec,
    metrics,
)


class _Store:
    def load_activation_state(self, memory_id):
        return None

    def load_priming_weight(self, memory_id):
        return 0.0

    def record_activation_shadow(self, result, *, trace_id):
        return "actevt-test"

    def record_priming_shadow(self, **kwargs):
        return "prime-test"

    def record_salience_shadow(self, **kwargs):
        return "sal-test"


def test_phase2_observability_contract_contains_required_metrics_without_content():
    spec = cognitive_observability_spec()
    assert "memory_activation_total" in spec["metrics"]
    assert "priming_events_total" in spec["metrics"]
    assert spec["contains_memory_content"] is False
    assert spec["contains_memory_identifiers"] is False


def test_phase2_metrics_increment_for_shadow_activation():
    metrics.reset_for_test()
    observer = CognitiveShadowObserver(_Store(), priming_enabled=False, salience_enabled=False)
    observer.observe_retrieval(
        selected=({"item_id": "mem-1", "confidence": 0.7, "created_at": "2026-09-24T20:00:00+00:00"},),
        trace_id="trace-test",
    )
    assert metrics.snapshot()["memory_activation_total"] == 1


def test_phase2_feature_flags_default_off(monkeypatch):
    for name in ("COGNITIVE_ACTIVATION", "COGNITIVE_PRIMING", "COGNITIVE_SALIENCE"):
        monkeypatch.delenv(name, raising=False)
    assert get_cognitive_shadow_observer(_Store()) is None


def test_phase2_feature_flag_enables_shadow_observer_without_public_cognitive_api(monkeypatch):
    monkeypatch.setenv("COGNITIVE_ACTIVATION", "1")
    monkeypatch.delenv("COGNITIVE_PRIMING", raising=False)
    monkeypatch.delenv("COGNITIVE_SALIENCE", raising=False)
    observer = get_cognitive_shadow_observer(_Store())
    assert observer is not None
    assert observer.activation_enabled is True
    assert observer.priming_enabled is False
    paths = [getattr(route, "path", "") for route in app.routes]
    assert not any(path.startswith("/v1/cognitive") for path in paths)
