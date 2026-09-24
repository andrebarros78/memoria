from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

COGNITIVE_CONTRACT_VERSION = "CKC-1.1.0"
MAX_IDENTIFIER_LENGTH = 128
MAX_SOURCE_REF_LENGTH = 512
MAX_EVIDENCE_REFS = 64
MAX_ATTRIBUTE_KEYS = 64


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


class CognitiveOperation(StrEnum):
    ACTIVATE = "memory.activate"
    ASSOCIATE = "memory.associate"
    REACTIVATE = "memory.reactivate"
    RECONSOLIDATE = "memory.reconsolidate"
    CONSOLIDATE = "memory.consolidate"
    GENERALIZE = "memory.generalize"
    INTENT_CREATE = "memory.intent.create"
    INTENT_EVALUATE = "memory.intent.evaluate"
    INTENT_COMPLETE = "memory.intent.complete"
    WORLD_OBSERVE = "memory.world.observe"
    WORLD_TRANSITION = "memory.world.transition"
    EXPLAIN = "memory.explain"
    METACOGNITION = "memory.metacognition"


class CognitiveEventType(StrEnum):
    MEMORY_CAPTURED = "MEMORY_CAPTURED"
    MEMORY_RETRIEVED = "MEMORY_RETRIEVED"
    MEMORY_ACTIVATED = "MEMORY_ACTIVATED"
    MEMORY_PRIMED = "MEMORY_PRIMED"
    MEMORY_REACTIVATED = "MEMORY_REACTIVATED"
    MEMORY_RECONSOLIDATED = "MEMORY_RECONSOLIDATED"
    MEMORY_ASSOCIATED = "MEMORY_ASSOCIATED"
    MEMORY_CONSOLIDATION_STARTED = "MEMORY_CONSOLIDATION_STARTED"
    MEMORY_CONSOLIDATION_FINISHED = "MEMORY_CONSOLIDATION_FINISHED"
    CONCEPT_CANDIDATE_CREATED = "CONCEPT_CANDIDATE_CREATED"
    CONCEPT_PROMOTED = "CONCEPT_PROMOTED"
    INTENTION_ARMED = "INTENTION_ARMED"
    INTENTION_TRIGGERED = "INTENTION_TRIGGERED"
    INTENTION_COMPLETED = "INTENTION_COMPLETED"
    EMBODIED_EPISODE_CAPTURED = "EMBODIED_EPISODE_CAPTURED"
    MEMORY_WEAKENED = "MEMORY_WEAKENED"
    MEMORY_ARCHIVED = "MEMORY_ARCHIVED"


class CognitiveFeature(StrEnum):
    COGNITIVE_ACTIVATION = "COGNITIVE_ACTIVATION"
    COGNITIVE_PRIMING = "COGNITIVE_PRIMING"
    COGNITIVE_SALIENCE = "COGNITIVE_SALIENCE"
    COGNITIVE_ASSOCIATION = "COGNITIVE_ASSOCIATION"
    COGNITIVE_CONSOLIDATION = "COGNITIVE_CONSOLIDATION"
    COGNITIVE_RECONSOLIDATION = "COGNITIVE_RECONSOLIDATION"
    COGNITIVE_GENERALIZATION = "COGNITIVE_GENERALIZATION"
    COGNITIVE_PROSPECTIVE = "COGNITIVE_PROSPECTIVE"
    COGNITIVE_EMBODIED = "COGNITIVE_EMBODIED"


def default_cognitive_feature_flags() -> Mapping[str, bool]:
    return MappingProxyType({feature.value: False for feature in CognitiveFeature})


def _normalize_identifier(name: str, value: str | None, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{name} is required")
        return None
    normalized = str(value).strip()
    if not normalized:
        if required:
            raise ValueError(f"{name} is required")
        return None
    if len(normalized) > MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"{name} exceeds maximum length")
    if any(ord(char) < 32 for char in normalized):
        raise ValueError(f"{name} contains control characters")
    return normalized


@dataclass(frozen=True, slots=True)
class CognitiveScope:
    tenant_id: str
    owner_id: str
    project_id: str | None = None
    mission_id: str | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _normalize_identifier("tenant_id", self.tenant_id, required=True))
        object.__setattr__(self, "owner_id", _normalize_identifier("owner_id", self.owner_id, required=True))
        for name in ("project_id", "mission_id", "session_id"):
            object.__setattr__(self, name, _normalize_identifier(name, getattr(self, name), required=False))


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
        source_ref = str(self.source_ref).strip()
        if not source_ref:
            raise ValueError("source_ref is required")
        if len(source_ref) > MAX_SOURCE_REF_LENGTH:
            raise ValueError("source_ref exceeds maximum length")
        if any(ord(char) < 32 for char in source_ref):
            raise ValueError("source_ref contains control characters")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if not isinstance(self.attributes, Mapping):
            raise ValueError("attributes must be a mapping")
        if len(self.attributes) > MAX_ATTRIBUTE_KEYS:
            raise ValueError("attributes exceed maximum key count")
        normalized_refs: list[str] = []
        for raw_ref in self.evidence_refs:
            if not isinstance(raw_ref, str):
                raise ValueError("evidence_refs must contain strings")
            ref = raw_ref.strip()
            if not ref:
                continue
            if len(ref) > MAX_SOURCE_REF_LENGTH or any(ord(char) < 32 for char in ref):
                raise ValueError("invalid evidence_ref")
            if ref not in normalized_refs:
                normalized_refs.append(ref)
        if len(normalized_refs) > MAX_EVIDENCE_REFS:
            raise ValueError("too many evidence_refs")
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))
        object.__setattr__(self, "evidence_refs", tuple(normalized_refs))


@dataclass(frozen=True, slots=True)
class CognitiveEvaluation:
    contract_version: str
    decision: CognitiveDecision
    accepted: bool
    reasons: tuple[str, ...]
    trace: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace", MappingProxyType(dict(self.trace)))


class MemoryStorePort(Protocol):
    """Marker contract; concrete methods arrive with capability conformance."""


class GraphStorePort(Protocol):
    """Marker contract; concrete methods arrive with capability conformance."""


class VectorStorePort(Protocol):
    """Marker contract; concrete methods arrive with capability conformance."""


class CheckpointStorePort(Protocol):
    """Marker contract; concrete methods arrive with capability conformance."""


class ActivationStorePort(Protocol):
    """Marker contract; concrete methods arrive in the activation phase."""


class ProspectiveStorePort(Protocol):
    """Marker contract; concrete methods arrive in the prospective phase."""


class AuditStorePort(Protocol):
    """Marker contract; concrete methods arrive with audit conformance."""


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
        "feature_flags": dict(default_cognitive_feature_flags()),
        "proposed_operations": [operation.value for operation in CognitiveOperation],
        "event_types": [event.value for event in CognitiveEventType],
        "storage_ports": [
            "MemoryStorePort",
            "GraphStorePort",
            "VectorStorePort",
            "CheckpointStorePort",
            "ActivationStorePort",
            "ProspectiveStorePort",
            "AuditStorePort",
        ],
        "principles": [
            "cognition_is_separate_from_memory_truth",
            "new_engines_default_to_shadow",
            "all_outputs_are_traceable",
            "scope_isolation_is_fail_closed",
            "evidence_precedes_promotion",
            "core_remains_operational_when_cognition_is_disabled",
        ],
    }
