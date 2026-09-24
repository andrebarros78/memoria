from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

COGNITIVE_CONTRACT_VERSION = "CKC-1.0.0"


class CognitiveMode(StrEnum):
    SHADOW = "SHADOW"
    ENABLED = "ENABLED"


class CognitiveSignalType(StrEnum):
    ACTIVATION = "ACTIVATION"
    PRIMING = "PRIMING"
    SALIENCE = "SALIENCE"
    ASSOCIATION = "ASSOCIATION"
    CONSOLIDATION = "CONSOLIDATION"
    RECONSOLIDATION = "RECONSOLIDATION"
    GENERALIZATION = "GENERALIZATION"
    PROSPECTIVE = "PROSPECTIVE"
    EMBODIED = "EMBODIED"


class CognitiveDecision(StrEnum):
    OBSERVE = "OBSERVE"
    SUGGEST = "SUGGEST"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class CognitiveScope:
    tenant_id: str
    owner_id: str
    project_id: str | None = None
    mission_id: str | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("tenant_id", "owner_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")


@dataclass(frozen=True, slots=True)
class CognitiveEnvelope:
    signal_type: CognitiveSignalType
    scope: CognitiveScope
    source_ref: str
    evidence_refs: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)
    mode: CognitiveMode = CognitiveMode.SHADOW
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.source_ref.strip():
            raise ValueError("source_ref is required")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        object.__setattr__(self, "attributes", dict(self.attributes))
        object.__setattr__(self, "evidence_refs", tuple(dict.fromkeys(x.strip() for x in self.evidence_refs if x.strip())))


@dataclass(frozen=True, slots=True)
class CognitiveEvaluation:
    contract_version: str
    decision: CognitiveDecision
    accepted: bool
    reasons: tuple[str, ...]
    trace: Mapping[str, Any]


def cognitive_contract_spec() -> dict[str, Any]:
    return {
        "version": COGNITIVE_CONTRACT_VERSION,
        "default_mode": CognitiveMode.SHADOW.value,
        "mutation_authority": "NONE",
        "truth_mutation_allowed": False,
        "direct_promotion_allowed": False,
        "cross_scope_activation_allowed": False,
        "consumer_assigned_final_salience_allowed": False,
        "required_scope": ["tenant_id", "owner_id"],
        "principles": [
            "cognition_is_separate_from_memory_truth",
            "new_engines_default_to_shadow",
            "all_outputs_are_traceable",
            "scope_isolation_is_fail_closed",
            "evidence_precedes_promotion",
            "core_remains_operational_when_cognition_is_disabled",
        ],
    }
