from __future__ import annotations

import time

import pytest

from memory_permanent.association_policy import (
    AssociationLimits,
    AssociationRelation,
    association_policy_spec,
    evidence_filter,
    weighted_relation_strength,
)
from memory_permanent.associative_memory import association_store_spec
from memory_permanent.spreading_activation import (
    AssociationNeighbor,
    SpreadingActivationEngine,
)


def _edge(
    memory_id: str,
    relation: AssociationRelation,
    weight: float,
    *,
    evidence_strength: float = 1.0,
    source_ref: str | None = None,
) -> AssociationNeighbor:
    return AssociationNeighbor(
        memory_id=memory_id,
        relation_type=relation,
        weight=weight,
        evidence_strength=evidence_strength,
        source_kind="TEST",
        source_ref=source_ref or f"edge:{memory_id}:{relation.value}",
        evidence={"proof": True},
    )


def test_phase3_policy_declares_all_executive_relation_types_and_shadow_mode():
    spec = association_policy_spec()
    assert spec["mode"] == "SHADOW"
    assert spec["truth_mutation_allowed"] is False
    assert spec["loop_protection"] is True
    assert spec["deterministic_trace"] is True
    assert set(spec["relation_types"]) == {relation.value for relation in AssociationRelation}
    assert len(spec["relation_types"]) == 13


def test_phase3_limits_are_bounded_fail_fast():
    with pytest.raises(ValueError):
        AssociationLimits(max_depth=5)
    with pytest.raises(ValueError):
        AssociationLimits(node_budget=257)
    with pytest.raises(ValueError):
        AssociationLimits(time_budget_ms=0)
    with pytest.raises(ValueError):
        AssociationLimits(max_candidates=129)


def test_phase3_relation_strength_is_bounded_and_evidence_aware():
    assert weighted_relation_strength(AssociationRelation.CAUSAL_RELATION, observed_strength=0.8) == pytest.approx(0.76)
    assert weighted_relation_strength(AssociationRelation.SEMANTIC_SIMILARITY, observed_strength=0.91) == pytest.approx(0.91)
    assert evidence_filter(AssociationRelation.CAUSAL_RELATION, evidence_strength=0.49) == (
        False,
        "INSUFFICIENT_EVIDENCE",
    )
    assert evidence_filter(AssociationRelation.SHARED_CONTEXT, evidence_strength=0.0) == (True, "ALLOWED")


def test_phase3_spreading_activation_is_deterministic_bounded_and_loop_safe():
    graph = {
        "A": (
            _edge("B", AssociationRelation.SUPPORT, 0.90, source_ref="ab"),
            _edge("D", AssociationRelation.CONTRADICTION, 0.80, evidence_strength=0.30, source_ref="ad"),
        ),
        "B": (_edge("C", AssociationRelation.SEMANTIC_SIMILARITY, 0.80, source_ref="bc"),),
        "C": (_edge("A", AssociationRelation.SHARED_CONTEXT, 0.75, source_ref="ca"),),
        "D": (),
    }
    engine = SpreadingActivationEngine(
        AssociationLimits(max_depth=3, node_budget=16, time_budget_ms=1000, max_candidates=8)
    )
    provider = lambda memory_id, _depth: graph.get(memory_id, ())
    first = engine.traverse(("A",), provider)
    second = engine.traverse(("A",), provider)
    assert first.deterministic_trace == second.deterministic_trace
    assert [candidate.memory_id for candidate in first.candidates] == ["B", "C"]
    assert first.candidates[0].activation_score == pytest.approx(0.90)
    assert first.candidates[1].activation_score == pytest.approx(0.90 * 0.80 * 0.72)
    assert first.evidence_rejections == 1
    assert first.loops_blocked == 1
    assert first.visited_count == 3
    assert all(candidate.hop_depth <= 3 for candidate in first.candidates)


def test_phase3_node_budget_stops_traversal_without_unbounded_expansion():
    graph = {
        "A": tuple(_edge(f"N{i}", AssociationRelation.SHARED_CONTEXT, 0.8, source_ref=f"a{i}") for i in range(20))
    }
    engine = SpreadingActivationEngine(
        AssociationLimits(max_depth=2, node_budget=5, time_budget_ms=1000, max_candidates=32)
    )
    result = engine.traverse(("A",), lambda memory_id, _depth: graph.get(memory_id, ()))
    assert result.budget_exhausted is True
    assert result.considered_edges == 5
    assert len(result.candidates) <= 5


def test_phase3_time_budget_stops_slow_traversal():
    engine = SpreadingActivationEngine(
        AssociationLimits(max_depth=2, node_budget=16, time_budget_ms=1, max_candidates=8)
    )

    def provider(memory_id, _depth):
        time.sleep(0.005)
        if memory_id == "A":
            return (_edge("B", AssociationRelation.SHARED_CONTEXT, 0.9),)
        return ()

    first = engine.traverse(("A",), provider)
    second = engine.traverse(("A",), provider)
    assert first.time_budget_exhausted is True
    assert first.candidates == ()
    assert first.visited_count == 1
    assert first.considered_edges == 0
    assert first.deterministic_trace == second.deterministic_trace


def test_phase3_store_contract_uses_only_canonical_evidence_sources():
    spec = association_store_spec()
    assert spec["persists_inferred_truth"] is False
    assert spec["persists_traversal_trace"] is True
    assert spec["canonical_sources"] == ["ONTOLOGY", "EXPERIENCE_GRAPH", "PGVECTOR"]
    assert spec["native_relation_mappings"]["ontology"]["CAUSES"] == "CAUSAL_RELATION"
    assert spec["native_relation_mappings"]["experience_graph"]["INFORMS"] == "DECISION_DEPENDENCY"
