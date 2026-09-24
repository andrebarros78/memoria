from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CognitiveState(StrEnum):
    CANDIDATE = "CANDIDATE"
    SHADOW = "SHADOW"
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


class CognitiveRelation(StrEnum):
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


@dataclass(frozen=True, slots=True)
class BoundedScore:
    value: float

    def __post_init__(self) -> None:
        value = float(self.value)
        if not 0.0 <= value <= 1.0:
            raise ValueError("score must be between 0 and 1")
        object.__setattr__(self, "value", value)
