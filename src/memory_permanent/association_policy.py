from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

ASSOCIATION_POLICY_VERSION = "ASP-1.0.0"


class AssociationRelation(StrEnum):
    SEMANTIC_SIMILARITY = "SEMANTIC_SIMILARITY"
    TEMPORAL_PROXIMITY = "TEMPORAL_PROXIMITY"
    CAUSAL_RELATION = "CAUSAL_RELATION"
    SHARED_ENTITY = "SHARED_ENTITY"
    SHARED_PERSON = "SHARED_PERSON"
    SHARED_OBJECTIVE = "SHARED_OBJECTIVE"
    SHARED_CONTEXT = "SHARED_CONTEXT"
    SHARED_OUTCOME = "SHARED_OUTCOME"
    CO_OCCURRENCE = "CO_OCCURRENCE"
    PROCEDURAL_DEPENDENCY = "PROCEDURAL_DEPENDENCY"
    DECISION_DEPENDENCY = "DECISION_DEPENDENCY"
    CONTRADICTION = "CONTRADICTION"
    SUPPORT = "SUPPORT"


RELATION_BASE_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        AssociationRelation.SEMANTIC_SIMILARITY.value: 1.00,
        AssociationRelation.TEMPORAL_PROXIMITY.value: 0.70,
        AssociationRelation.CAUSAL_RELATION.value: 0.95,
        AssociationRelation.SHARED_ENTITY.value: 0.75,
        AssociationRelation.SHARED_PERSON.value: 0.78,
        AssociationRelation.SHARED_OBJECTIVE.value: 0.82,
        AssociationRelation.SHARED_CONTEXT.value: 0.74,
        AssociationRelation.SHARED_OUTCOME.value: 0.82,
        AssociationRelation.CO_OCCURRENCE.value: 0.72,
        AssociationRelation.PROCEDURAL_DEPENDENCY.value: 0.90,
        AssociationRelation.DECISION_DEPENDENCY.value: 0.90,
        AssociationRelation.CONTRADICTION.value: 0.85,
        AssociationRelation.SUPPORT.value: 0.90,
    }
)

_HIGH_EVIDENCE_RELATIONS = frozenset(
    {
        AssociationRelation.CAUSAL_RELATION,
        AssociationRelation.CONTRADICTION,
        AssociationRelation.SUPPORT,
        AssociationRelation.DECISION_DEPENDENCY,
        AssociationRelation.PROCEDURAL_DEPENDENCY,
    }
)


@dataclass(frozen=True, slots=True)
class AssociationLimits:
    max_depth: int = 2
    node_budget: int = 64
    time_budget_ms: int = 1000
    max_candidates: int = 32
    hop_decay: float = 0.72
    min_activation: float = 0.12
    semantic_min_similarity: float = 0.72

    def __post_init__(self) -> None:
        if not 1 <= int(self.max_depth) <= 4:
            raise ValueError("max_depth must be between 1 and 4")
        if not 1 <= int(self.node_budget) <= 256:
            raise ValueError("node_budget must be between 1 and 256")
        if not 1 <= int(self.time_budget_ms) <= 1000:
            raise ValueError("time_budget_ms must be between 1 and 1000")
        if not 1 <= int(self.max_candidates) <= 128:
            raise ValueError("max_candidates must be between 1 and 128")
        if not 0.0 < float(self.hop_decay) <= 1.0:
            raise ValueError("hop_decay must be in (0, 1]")
        if not 0.0 <= float(self.min_activation) <= 1.0:
            raise ValueError("min_activation must be in [0, 1]")
        if not 0.0 <= float(self.semantic_min_similarity) <= 1.0:
            raise ValueError("semantic_min_similarity must be in [0, 1]")


def normalize_relation(value: AssociationRelation | str) -> AssociationRelation:
    if isinstance(value, AssociationRelation):
        return value
    return AssociationRelation(str(value).strip().upper())


def weighted_relation_strength(
    relation: AssociationRelation | str,
    *,
    observed_strength: float = 1.0,
) -> float:
    rel = normalize_relation(relation)
    observed = max(0.0, min(1.0, float(observed_strength)))
    return max(0.0, min(1.0, RELATION_BASE_WEIGHTS[rel.value] * observed))


def evidence_filter(
    relation: AssociationRelation | str,
    *,
    evidence_strength: float,
) -> tuple[bool, str]:
    rel = normalize_relation(relation)
    strength = max(0.0, min(1.0, float(evidence_strength)))
    minimum = 0.50 if rel in _HIGH_EVIDENCE_RELATIONS else 0.0
    if strength < minimum:
        return False, "INSUFFICIENT_EVIDENCE"
    return True, "ALLOWED"


def association_policy_spec() -> dict[str, object]:
    defaults = AssociationLimits()
    return {
        "version": ASSOCIATION_POLICY_VERSION,
        "mode": "SHADOW",
        "truth_mutation_allowed": False,
        "relation_types": [relation.value for relation in AssociationRelation],
        "relation_base_weights": dict(RELATION_BASE_WEIGHTS),
        "limits": {
            "max_depth": defaults.max_depth,
            "node_budget": defaults.node_budget,
            "time_budget_ms": defaults.time_budget_ms,
            "max_candidates": defaults.max_candidates,
            "hop_decay": defaults.hop_decay,
            "min_activation": defaults.min_activation,
            "semantic_min_similarity": defaults.semantic_min_similarity,
        },
        "loop_protection": True,
        "deterministic_trace": True,
        "scope_filter": "FAIL_CLOSED",
        "conflict_evidence_filter": True,
    }
