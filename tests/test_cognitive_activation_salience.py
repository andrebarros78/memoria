from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from memory_permanent.cognitive_activation import (
    CognitiveActivationEngine,
    CognitiveShadowObserver,
)
from memory_permanent.cognitive_contracts import CognitiveScope
from memory_permanent.interference_policy import evaluate_interference
from memory_permanent.priming_policy import MAX_PRIMING_BOOST, evaluate_priming
from memory_permanent.salience_engine import SalienceEngine
from memory_permanent.salience_policy import SALIENCE_DIMENSIONS


def test_activation_score_is_deterministic_bounded_and_traceable():
    now = datetime(2026, 9, 24, 20, 0, tzinfo=UTC)
    engine = CognitiveActivationEngine(half_life_hours=72)
    kwargs = dict(
        memory_id="mem-1",
        base_strength=0.8,
        last_activated_at=now - timedelta(hours=6),
        access_count=12,
        priming_weight=0.10,
        association_activation=0.4,
        goal_relevance=0.7,
        context_match=0.8,
        interference_penalty=0.05,
        habituation_penalty=0.02,
        now=now,
        trace_id="trace-1",
    )
    a = engine.compute(**kwargs)
    b = engine.compute(**kwargs)
    assert a.activation_level == b.activation_level
    assert 0.0 <= a.activation_level <= 1.0
    assert set(a.trace.components) == {
        "base_strength",
        "recency_boost",
        "frequency_boost",
        "priming_boost",
        "context_match",
        "goal_relevance",
        "associative_activation",
        "temporal_decay",
        "interference",
        "habituation",
    }
    assert a.trace.truth_mutated is False
    assert a.trace.promotion_performed is False


def test_activation_decay_reduces_accessibility_without_deleting_memory():
    now = datetime(2026, 9, 24, 20, 0, tzinfo=UTC)
    engine = CognitiveActivationEngine(half_life_hours=24)
    recent = engine.compute(
        memory_id="mem-1", base_strength=0.7, last_activated_at=now - timedelta(hours=1), access_count=3, now=now
    )
    old = engine.compute(
        memory_id="mem-1", base_strength=0.7, last_activated_at=now - timedelta(days=14), access_count=3, now=now
    )
    assert recent.activation_level > old.activation_level
    assert old.trace.truth_mutated is False


def test_priming_enforces_scope_trust_budget_and_activation_cap():
    scope = CognitiveScope("tenant-a", "user-a", project_id="p1")
    allowed = evaluate_priming(
        source_scope=scope,
        target_scope=scope,
        requested_boost=0.9,
        source_trust=0.8,
        budget_remaining=0.5,
        evidence_refs=("e1",),
    )
    assert allowed.allowed is True
    assert allowed.boost == MAX_PRIMING_BOOST
    assert allowed.abuse_detected is True
    assert "priming_request_capped" in allowed.reasons

    blocked = evaluate_priming(
        source_scope=scope,
        target_scope=CognitiveScope("tenant-b", "user-a", project_id="p1"),
        requested_boost=0.1,
        source_trust=1.0,
        budget_remaining=1.0,
    )
    assert blocked.allowed is False
    assert blocked.boost == 0.0
    assert "scope_mismatch" in blocked.reasons


def test_priming_rejects_untrusted_source():
    scope = CognitiveScope("tenant-a", "user-a")
    result = evaluate_priming(
        source_scope=scope,
        target_scope=scope,
        requested_boost=0.1,
        source_trust=0.1,
        budget_remaining=1.0,
    )
    assert result.allowed is False
    assert "source_trust_below_threshold" in result.reasons


def test_interference_and_habituation_are_bounded():
    result = evaluate_interference(
        proactive_similarity=1.0,
        retroactive_similarity=1.0,
        contradiction_strength=1.0,
        habituation_signal=1.0,
    )
    assert result.interference_penalty == 0.25
    assert result.habituation_penalty == 0.10


def test_salience_is_deterministic_bounded_explainable_and_evidence_limited():
    engine = SalienceEngine()
    dimensions = {name: 0.0 for name in SALIENCE_DIMENSIONS}
    dimensions.update({"risk": 1.0, "urgency": 0.9, "safety_impact": 1.0, "irreversibility": 0.8})
    a = engine.compute(dimensions, source_trust=1.0, independent_evidence_count=0)
    b = engine.compute(dimensions, source_trust=1.0, independent_evidence_count=0)
    assert a.score == b.score
    assert 0.0 <= a.score <= 0.60
    assert a.explanation.evidence_limited is True
    assert a.explanation.top_dimensions[0][0] in {"risk", "safety_impact"}
    assert a.explanation.as_dict()["truth_mutated"] is False


def test_salience_rejects_consumer_assigned_final_score_and_unknown_dimensions():
    engine = SalienceEngine()
    with pytest.raises(ValueError, match="consumer-assigned final salience"):
        engine.compute({"risk": 0.4}, source_trust=1.0, independent_evidence_count=2, consumer_final_score=1.0)
    with pytest.raises(ValueError, match="unknown salience dimensions"):
        engine.compute({"emotion": 1.0}, source_trust=1.0, independent_evidence_count=2)


class _FakeCognitiveStore:
    def __init__(self) -> None:
        self.states: dict[str, object] = {}
        self.activations = []
        self.priming = []
        self.salience = []

    def load_activation_state(self, memory_id: str):
        return self.states.get(memory_id)

    def load_priming_weight(self, memory_id: str) -> float:
        return 0.05

    def record_activation_shadow(self, result, *, trace_id):
        self.activations.append((result, trace_id))
        return "actevt-test"

    def record_priming_shadow(self, **kwargs):
        self.priming.append(kwargs)
        return "prime-test"

    def record_salience_shadow(self, **kwargs):
        self.salience.append(kwargs)
        return "sal-test"


def test_shadow_observer_records_activation_without_changing_item():
    store = _FakeCognitiveStore()
    observer = CognitiveShadowObserver(store, salience_enabled=False)
    selected = ({"item_id": "mem-1", "confidence": 0.8, "created_at": "2026-09-24T18:00:00+00:00"},)
    before = dict(selected[0])
    observer.observe_retrieval(selected=selected, trace_id="trace-1")
    assert dict(selected[0]) == before
    assert len(store.activations) == 1
    assert store.activations[0][0].trace.truth_mutated is False


def test_shadow_observer_priming_records_only_allowed_decision():
    store = _FakeCognitiveStore()
    observer = CognitiveShadowObserver(store)
    scope = CognitiveScope("tenant-a", "user-a")
    allowed = observer.prime(
        target_memory_id="mem-1",
        source_scope=scope,
        target_scope=scope,
        requested_boost=0.1,
        source_trust=1.0,
        budget_remaining=1.0,
        evidence_refs=("e1",),
    )
    assert allowed.allowed is True
    assert len(store.priming) == 1
    blocked = observer.prime(
        target_memory_id="mem-1",
        source_scope=scope,
        target_scope=CognitiveScope("other", "user-a"),
        requested_boost=0.1,
        source_trust=1.0,
        budget_remaining=1.0,
    )
    assert blocked.allowed is False
    assert len(store.priming) == 1


def test_shadow_observer_capture_initializes_activation_and_explicit_salience_only():
    metrics_store = _FakeCognitiveStore()
    observer = CognitiveShadowObserver(metrics_store)
    observer.observe_capture(
        memory_id="mem-capture",
        base_strength=0.75,
        salience_signals={"risk": 0.8, "urgency": 0.7},
        source_trust=0.5,
        evidence_refs=("e1", "e2"),
    )
    assert len(metrics_store.activations) == 1
    assert metrics_store.activations[0][0].access_count == 0
    assert len(metrics_store.salience) == 1
    assert metrics_store.salience[0]["result"].mode == "SHADOW"
