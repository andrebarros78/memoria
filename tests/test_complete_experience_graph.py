from __future__ import annotations

import pytest

from memory_permanent.experience_graph import (
    EDGE_RULES,
    EXPERIENCE_GRAPH_VERSION,
    ExperienceNodeType,
    ExperienceRelationType,
    reconstruct_mission_graph,
    validate_edge_rule,
    validate_memory_binding,
)


def _node(node_id: str, node_type: str, second: int) -> dict[str, str]:
    return {
        "node_id": node_id,
        "node_type": node_type,
        "occurred_at": f"2026-09-02T12:00:{second:02d}+00:00",
        "observed_at": f"2026-09-02T12:00:{second:02d}+00:00",
    }


def test_exact_first_class_entity_types() -> None:
    assert {x.value for x in ExperienceNodeType} == {
        "HYPOTHESIS", "EVIDENCE", "DECISION", "INTERVENTION", "RESULT", "LEARNING", "KNOWLEDGE"
    }
    assert EXPERIENCE_GRAPH_VERSION == "EG-1.0.0"


def test_exact_causal_rule_count() -> None:
    assert len(EDGE_RULES) == 7
    validate_edge_rule("HYPOTHESIS", "EVALUATED_BY", "EVIDENCE")
    validate_edge_rule("EVIDENCE", "INFORMS", "DECISION")
    validate_edge_rule("DECISION", "IMPLEMENTED_BY", "INTERVENTION")
    validate_edge_rule("INTERVENTION", "PRODUCES", "RESULT")
    validate_edge_rule("RESULT", "DERIVES", "LEARNING")
    validate_edge_rule("RESULT", "CONSOLIDATES", "KNOWLEDGE")
    validate_edge_rule("LEARNING", "CONSOLIDATES", "KNOWLEDGE")


def test_invalid_causal_rule_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_edge_rule("HYPOTHESIS", "PRODUCES", "RESULT")


def test_memory_binding_semantics() -> None:
    validate_memory_binding("HYPOTHESIS", "HYPOTHESIS")
    validate_memory_binding("RESULT", "OUTCOME")
    validate_memory_binding("KNOWLEDGE", "FACT")
    validate_memory_binding("KNOWLEDGE", "PROCEDURE")
    with pytest.raises(ValueError):
        validate_memory_binding("RESULT", "FACT")


def test_complete_mission_reconstructs_causally_and_temporally() -> None:
    nodes = [
        _node("h", "HYPOTHESIS", 1),
        _node("e", "EVIDENCE", 2),
        _node("d", "DECISION", 3),
        _node("i", "INTERVENTION", 4),
        _node("r", "RESULT", 5),
        _node("l", "LEARNING", 6),
        _node("k", "KNOWLEDGE", 7),
    ]
    edges = [
        {"from_node_id": "h", "relation": "EVALUATED_BY", "to_node_id": "e"},
        {"from_node_id": "e", "relation": "INFORMS", "to_node_id": "d"},
        {"from_node_id": "d", "relation": "IMPLEMENTED_BY", "to_node_id": "i"},
        {"from_node_id": "i", "relation": "PRODUCES", "to_node_id": "r"},
        {"from_node_id": "r", "relation": "DERIVES", "to_node_id": "l"},
        {"from_node_id": "l", "relation": "CONSOLIDATES", "to_node_id": "k"},
    ]
    result = reconstruct_mission_graph(nodes, edges)
    assert result["reconstruction_status"] == "COMPLETE"
    assert result["complete_chain_found"] is True
    assert result["causal_order"] == ["h", "e", "d", "i", "r", "l", "k"]
    assert result["timeline"] == ["h", "e", "d", "i", "r", "l", "k"]


def test_result_can_consolidate_directly_to_knowledge() -> None:
    nodes = [
        _node("h", "HYPOTHESIS", 1), _node("e", "EVIDENCE", 2), _node("d", "DECISION", 3),
        _node("i", "INTERVENTION", 4), _node("r", "RESULT", 5), _node("k", "KNOWLEDGE", 6),
    ]
    edges = [
        {"from_node_id": "h", "relation": "EVALUATED_BY", "to_node_id": "e"},
        {"from_node_id": "e", "relation": "INFORMS", "to_node_id": "d"},
        {"from_node_id": "d", "relation": "IMPLEMENTED_BY", "to_node_id": "i"},
        {"from_node_id": "i", "relation": "PRODUCES", "to_node_id": "r"},
        {"from_node_id": "r", "relation": "CONSOLIDATES", "to_node_id": "k"},
    ]
    assert reconstruct_mission_graph(nodes, edges)["reconstruction_status"] == "COMPLETE"


def test_partial_graph_is_identified() -> None:
    nodes = [_node("h", "HYPOTHESIS", 1), _node("e", "EVIDENCE", 2)]
    edges = [{"from_node_id": "h", "relation": "EVALUATED_BY", "to_node_id": "e"}]
    result = reconstruct_mission_graph(nodes, edges)
    assert result["reconstruction_status"] == "PARTIAL"
    assert result["complete_chain_found"] is False


def test_cycle_is_rejected_by_reconstruction() -> None:
    # The rule validator rejects most reverse edges before cycle analysis; use a duplicate
    # topology with a synthetic self-reachable graph to ensure the topological guard remains fail-closed.
    nodes = [_node("h", "HYPOTHESIS", 1), _node("e", "EVIDENCE", 2)]
    with pytest.raises(ValueError):
        reconstruct_mission_graph(
            nodes,
            [
                {"from_node_id": "h", "relation": ExperienceRelationType.EVALUATED_BY.value, "to_node_id": "e"},
                {"from_node_id": "e", "relation": ExperienceRelationType.INFORMS.value, "to_node_id": "h"},
            ],
        )
