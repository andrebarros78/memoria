from __future__ import annotations

from memory_permanent.cognitive_contracts import default_cognitive_feature_flags
from memory_permanent.cognitive_observability import (
    cognitive_observability_spec,
    metrics,
)


def test_phase4_feature_flag_is_defined_and_default_off():
    flags = dict(default_cognitive_feature_flags())
    assert "COGNITIVE_CONSOLIDATION" in flags
    assert flags["COGNITIVE_CONSOLIDATION"] is False


def test_phase4_observability_exposes_required_content_free_metrics():
    spec = cognitive_observability_spec()
    assert "consolidation_runs_total" in spec["metrics"]
    assert "consolidation_candidates_total" in spec["metrics"]
    assert spec["contains_memory_content"] is False
    assert spec["contains_memory_identifiers"] is False


def test_phase4_metrics_accept_consolidation_counters():
    metrics.reset_for_test()
    metrics.increment("consolidation_runs_total")
    metrics.increment("consolidation_candidates_total", 3)
    snapshot = metrics.snapshot()
    assert snapshot["consolidation_runs_total"] == 1
    assert snapshot["consolidation_candidates_total"] == 3
