from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from .ontology import KnowledgeType

EXPERIENCE_GRAPH_VERSION = "EG-1.0.0"


class ExperienceNodeType(StrEnum):
    HYPOTHESIS = "HYPOTHESIS"
    EVIDENCE = "EVIDENCE"
    DECISION = "DECISION"
    INTERVENTION = "INTERVENTION"
    RESULT = "RESULT"
    LEARNING = "LEARNING"
    KNOWLEDGE = "KNOWLEDGE"


class ExperienceRelationType(StrEnum):
    EVALUATED_BY = "EVALUATED_BY"
    INFORMS = "INFORMS"
    IMPLEMENTED_BY = "IMPLEMENTED_BY"
    PRODUCES = "PRODUCES"
    DERIVES = "DERIVES"
    CONSOLIDATES = "CONSOLIDATES"


EDGE_RULES = frozenset(
    {
        (ExperienceNodeType.HYPOTHESIS, ExperienceRelationType.EVALUATED_BY, ExperienceNodeType.EVIDENCE),
        (ExperienceNodeType.EVIDENCE, ExperienceRelationType.INFORMS, ExperienceNodeType.DECISION),
        (ExperienceNodeType.DECISION, ExperienceRelationType.IMPLEMENTED_BY, ExperienceNodeType.INTERVENTION),
        (ExperienceNodeType.INTERVENTION, ExperienceRelationType.PRODUCES, ExperienceNodeType.RESULT),
        (ExperienceNodeType.RESULT, ExperienceRelationType.DERIVES, ExperienceNodeType.LEARNING),
        (ExperienceNodeType.RESULT, ExperienceRelationType.CONSOLIDATES, ExperienceNodeType.KNOWLEDGE),
        (ExperienceNodeType.LEARNING, ExperienceRelationType.CONSOLIDATES, ExperienceNodeType.KNOWLEDGE),
    }
)


MEMORY_CATEGORY_BINDINGS: dict[ExperienceNodeType, frozenset[KnowledgeType] | None] = {
    ExperienceNodeType.HYPOTHESIS: frozenset({KnowledgeType.HYPOTHESIS}),
    ExperienceNodeType.EVIDENCE: frozenset({KnowledgeType.EVIDENCE}),
    ExperienceNodeType.DECISION: frozenset({KnowledgeType.DECISION}),
    ExperienceNodeType.INTERVENTION: frozenset({KnowledgeType.INTERVENTION}),
    ExperienceNodeType.RESULT: frozenset({KnowledgeType.OUTCOME}),
    ExperienceNodeType.LEARNING: frozenset({KnowledgeType.LEARNING}),
    ExperienceNodeType.KNOWLEDGE: None,
}


EXPECTED_STAGE_ORDER = (
    ExperienceNodeType.HYPOTHESIS,
    ExperienceNodeType.EVIDENCE,
    ExperienceNodeType.DECISION,
    ExperienceNodeType.INTERVENTION,
    ExperienceNodeType.RESULT,
)


def normalize_node_type(value: str | ExperienceNodeType) -> ExperienceNodeType:
    if isinstance(value, ExperienceNodeType):
        return value
    return ExperienceNodeType(str(value).strip().upper())


def normalize_edge_relation(value: str | ExperienceRelationType) -> ExperienceRelationType:
    if isinstance(value, ExperienceRelationType):
        return value
    return ExperienceRelationType(str(value).strip().upper())


def validate_edge_rule(
    source_type: str | ExperienceNodeType,
    relation: str | ExperienceRelationType,
    target_type: str | ExperienceNodeType,
) -> tuple[ExperienceNodeType, ExperienceRelationType, ExperienceNodeType]:
    src = normalize_node_type(source_type)
    rel = normalize_edge_relation(relation)
    dst = normalize_node_type(target_type)
    if (src, rel, dst) not in EDGE_RULES:
        raise ValueError(f"invalid experience graph edge: {src.value} {rel.value} {dst.value}")
    return src, rel, dst


def validate_memory_binding(node_type: str | ExperienceNodeType, category: str | KnowledgeType) -> None:
    node = normalize_node_type(node_type)
    knowledge = category if isinstance(category, KnowledgeType) else KnowledgeType(str(category).strip().upper())
    allowed = MEMORY_CATEGORY_BINDINGS[node]
    if allowed is not None and knowledge not in allowed:
        expected = ",".join(sorted(x.value for x in allowed))
        raise ValueError(
            f"experience node {node.value} cannot bind memory category {knowledge.value}; expected {expected}"
        )


def _stable_key(node: dict[str, Any]) -> tuple[str, str, str]:
    return (str(node.get("occurred_at") or ""), str(node.get("observed_at") or ""), str(node.get("node_id") or ""))


def _complete_chain_exists(nodes_by_id: dict[str, dict[str, Any]], adjacency: dict[str, list[str]]) -> bool:
    starts = [node_id for node_id, node in nodes_by_id.items() if node.get("node_type") == ExperienceNodeType.HYPOTHESIS.value]
    if not starts:
        return False
    terminal_types = {ExperienceNodeType.LEARNING.value, ExperienceNodeType.KNOWLEDGE.value}
    required_prefix = [x.value for x in EXPECTED_STAGE_ORDER]
    for start in starts:
        stack: list[tuple[str, tuple[str, ...]]] = [(start, (ExperienceNodeType.HYPOTHESIS.value,))]
        while stack:
            current, stages = stack.pop()
            for nxt in adjacency.get(current, []):
                nxt_type = str(nodes_by_id[nxt]["node_type"])
                next_stages = stages + (nxt_type,)
                if len(next_stages) <= len(required_prefix):
                    if list(next_stages) != required_prefix[: len(next_stages)]:
                        continue
                elif list(next_stages[: len(required_prefix)]) != required_prefix:
                    continue
                if len(next_stages) > len(required_prefix) and nxt_type in terminal_types:
                    return True
                stack.append((nxt, next_stages))
    return False


def reconstruct_mission_graph(nodes: Iterable[dict[str, Any]], edges: Iterable[dict[str, Any]]) -> dict[str, Any]:
    node_list = [dict(x) for x in nodes]
    edge_list = [dict(x) for x in edges]
    nodes_by_id = {str(x["node_id"]): x for x in node_list}
    indegree = {node_id: 0 for node_id in nodes_by_id}
    adjacency: dict[str, list[str]] = defaultdict(list)

    for edge in edge_list:
        source_id = str(edge["from_node_id"])
        target_id = str(edge["to_node_id"])
        if source_id not in nodes_by_id or target_id not in nodes_by_id:
            raise ValueError("experience graph edge references missing node")
        validate_edge_rule(nodes_by_id[source_id]["node_type"], edge["relation"], nodes_by_id[target_id]["node_type"])
        adjacency[source_id].append(target_id)
        indegree[target_id] += 1

    ready = sorted((nodes_by_id[node_id] for node_id, degree in indegree.items() if degree == 0), key=_stable_key)
    queue: deque[dict[str, Any]] = deque(ready)
    causal_order: list[str] = []
    while queue:
        node = queue.popleft()
        node_id = str(node["node_id"])
        causal_order.append(node_id)
        newly_ready: list[dict[str, Any]] = []
        for target_id in adjacency.get(node_id, []):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                newly_ready.append(nodes_by_id[target_id])
        if newly_ready:
            merged = list(queue) + newly_ready
            queue = deque(sorted(merged, key=_stable_key))

    if len(causal_order) != len(node_list):
        raise ValueError("experience graph contains a causal cycle")

    timeline = [str(node["node_id"]) for node in sorted(node_list, key=_stable_key)]
    return {
        "version": EXPERIENCE_GRAPH_VERSION,
        "node_count": len(node_list),
        "edge_count": len(edge_list),
        "causal_order": causal_order,
        "timeline": timeline,
        "complete_chain_found": _complete_chain_exists(nodes_by_id, adjacency),
        "reconstruction_status": "COMPLETE" if _complete_chain_exists(nodes_by_id, adjacency) else "PARTIAL",
    }


def experience_graph_spec() -> dict[str, Any]:
    return {
        "version": EXPERIENCE_GRAPH_VERSION,
        "node_types": [x.value for x in ExperienceNodeType],
        "relation_types": [x.value for x in ExperienceRelationType],
        "edge_rules": [
            {"source": source.value, "relation": relation.value, "target": target.value}
            for source, relation, target in sorted(EDGE_RULES, key=lambda x: (x[0].value, x[1].value, x[2].value))
        ],
        "memory_category_bindings": {
            node.value: (None if categories is None else sorted(x.value for x in categories))
            for node, categories in MEMORY_CATEGORY_BINDINGS.items()
        },
    }
