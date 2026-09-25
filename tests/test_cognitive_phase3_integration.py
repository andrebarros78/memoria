from __future__ import annotations

from memory_permanent.association_policy import AssociationLimits, AssociationRelation
from memory_permanent.cognitive_activation import CognitiveShadowObserver
from memory_permanent.cognitive_observability import dispatcher, metrics
from memory_permanent.context_engine import ContextEngine
from memory_permanent.spreading_activation import (
    AssociationNeighbor,
    SpreadingActivationEngine,
)


class _BaseStore:
    tenant_id = "TENANT-A"

    def __init__(self) -> None:
        self.trace_calls = 0

    def memory_candidates(self, query, namespaces, limit, **kwargs):
        return [
            {
                "item_id": "mem-seed",
                "namespace": namespaces[0],
                "memory_key": "seed",
                "content_sha256": "a" * 64,
                "confidence": 0.9,
                "source": "test",
                "operator_class": "ATIVA",
                "lifecycle_state": "HOT",
                "text_rank": 0.9,
                "exact_substring_match": True,
                "created_at": "2026-09-25T10:00:00+00:00",
            },
            {
                "item_id": "mem-base-second",
                "namespace": namespaces[0],
                "memory_key": "second",
                "content_sha256": "b" * 64,
                "confidence": 0.4,
                "source": "test",
                "operator_class": "ATIVA",
                "lifecycle_state": "HOT",
                "text_rank": 0.2,
                "exact_substring_match": False,
                "created_at": "2026-09-25T10:00:00+00:00",
            },
        ]

    def record_retrieval_trace(self, query, namespaces, candidates, selected, conflicts, **kwargs):
        self.trace_calls += 1
        return "trace-f03"

    def latest_checkpoint(self, mission_id, namespaces, **kwargs):
        return None


class _ActivationStore:
    def load_activation_state(self, memory_id):
        return None

    def load_priming_weight(self, memory_id):
        return 0.0

    def record_activation_shadow(self, result, *, trace_id):
        return "activation-test"

    def record_priming_shadow(self, **kwargs):
        return "priming-test"

    def record_salience_shadow(self, **kwargs):
        return "salience-test"


class _AssociationStore:
    def __init__(self) -> None:
        self.recorded = []
        self.scope_calls = []

    def neighbors(self, memory_id, *, namespaces, mission_id, session_id, semantic_min_similarity, limit):
        self.scope_calls.append((memory_id, tuple(namespaces), mission_id, session_id, semantic_min_similarity, limit))
        if memory_id == "mem-seed":
            return (
                AssociationNeighbor(
                    memory_id="mem-association-only",
                    relation_type=AssociationRelation.SUPPORT,
                    weight=0.9,
                    evidence_strength=1.0,
                    source_kind="TEST",
                    source_ref="assoc-edge",
                    evidence={"proof": True},
                ),
            )
        return ()

    def record_traversal_shadow(self, result, *, retrieval_trace_id, mission_id, session_id):
        self.recorded.append((result, retrieval_trace_id, mission_id, session_id))
        return "ast-test"


def test_phase3_association_runs_after_base_ranking_without_changing_selected_results():
    metrics.reset_for_test()
    base_store = _BaseStore()
    association_store = _AssociationStore()
    observer = CognitiveShadowObserver(
        _ActivationStore(),
        activation_enabled=False,
        priming_enabled=False,
        salience_enabled=False,
        association_enabled=True,
        association_store=association_store,
        spreading_engine=SpreadingActivationEngine(
            AssociationLimits(max_depth=2, node_budget=16, time_budget_ms=1000, max_candidates=8)
        ),
    )
    engine = ContextEngine(base_store, cognitive_observer=observer)
    result = engine.retrieve(
        "seed",
        namespaces=("F03",),
        limit=2,
        mission_id="mission-f03",
        session_id="session-f03",
    )
    assert [item["item_id"] for item in result.selected] == ["mem-seed", "mem-base-second"]
    assert "mem-association-only" not in {item["item_id"] for item in result.selected}
    assert dispatcher.wait_for_idle(5.0) is True
    assert len(association_store.recorded) == 1
    traversal, trace_id, mission_id, session_id = association_store.recorded[0]
    assert trace_id == "trace-f03"
    assert mission_id == "mission-f03"
    assert session_id == "session-f03"
    assert [candidate.memory_id for candidate in traversal.candidates] == ["mem-association-only"]
    assert metrics.snapshot()["association_traversals_total"] == 1
    assert association_store.scope_calls[0][1:4] == (("F03",), "mission-f03", "session-f03")


def test_phase3_association_failure_remains_inside_shadow_failure_domain():
    class _FailingAssociationStore(_AssociationStore):
        def neighbors(self, *args, **kwargs):
            raise RuntimeError("association backend unavailable")

    metrics.reset_for_test()
    base_store = _BaseStore()
    observer = CognitiveShadowObserver(
        _ActivationStore(),
        activation_enabled=False,
        priming_enabled=False,
        salience_enabled=False,
        association_enabled=True,
        association_store=_FailingAssociationStore(),
    )
    result = ContextEngine(base_store, cognitive_observer=observer).retrieve(
        "seed", namespaces=("F03",), limit=1
    )
    assert result.selected[0]["item_id"] == "mem-seed"
    assert dispatcher.wait_for_idle(5.0) is True
    assert metrics.snapshot()["cognitive_shadow_failures_total"] >= 1
