from __future__ import annotations

from memory_permanent.api import app, get_cognitive_shadow_observer
from memory_permanent.cognitive_observability import cognitive_observability_spec


class _Access:
    project_id = None


class _Store:
    tenant_id = "TENANT-A"
    access = _Access()


def test_phase3_observability_contract_exposes_association_metric_without_content():
    spec = cognitive_observability_spec()
    assert "association_traversals_total" in spec["metrics"]
    assert spec["mode"] == "SHADOW"
    assert spec["contains_memory_content"] is False
    assert spec["contains_memory_identifiers"] is False


def test_phase3_association_feature_flag_defaults_off(monkeypatch):
    for name in (
        "COGNITIVE_ACTIVATION",
        "COGNITIVE_PRIMING",
        "COGNITIVE_SALIENCE",
        "COGNITIVE_ASSOCIATION",
    ):
        monkeypatch.delenv(name, raising=False)
    assert get_cognitive_shadow_observer(_Store()) is None


def test_phase3_association_flag_enables_only_shadow_observer_and_no_public_cognitive_api(monkeypatch):
    for name in ("COGNITIVE_ACTIVATION", "COGNITIVE_PRIMING", "COGNITIVE_SALIENCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COGNITIVE_ASSOCIATION", "1")
    observer = get_cognitive_shadow_observer(_Store())
    assert observer is not None
    assert observer.association_enabled is True
    assert observer.activation_enabled is False
    assert observer.priming_enabled is False
    assert observer.salience_enabled is False
    paths = [getattr(route, "path", "") for route in app.routes]
    assert not any(path.startswith("/v1/cognitive") for path in paths)
