from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .cognitive_contracts import CognitiveScope

PRIMING_POLICY_VERSION = "PRM-1.0.0"
MAX_PRIMING_BOOST = 0.20
MIN_SOURCE_TRUST = 0.40
MAX_EVIDENCE_REFS = 64


def _unit(name: str, value: float) -> float:
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


def _same_scope(source: CognitiveScope, target: CognitiveScope) -> bool:
    return (
        source.tenant_id == target.tenant_id
        and source.owner_id == target.owner_id
        and source.project_id == target.project_id
        and source.mission_id == target.mission_id
        and source.session_id == target.session_id
    )


@dataclass(frozen=True, slots=True)
class PrimingDecision:
    allowed: bool
    boost: float
    reasons: tuple[str, ...]
    abuse_detected: bool
    trace: Mapping[str, Any]
    policy_version: str = PRIMING_POLICY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace", MappingProxyType(dict(self.trace)))


def evaluate_priming(
    *,
    source_scope: CognitiveScope,
    target_scope: CognitiveScope,
    requested_boost: float,
    source_trust: float,
    budget_remaining: float,
    evidence_refs: tuple[str, ...] = (),
) -> PrimingDecision:
    requested = _unit("requested_boost", requested_boost)
    trust = _unit("source_trust", source_trust)
    budget = _unit("budget_remaining", budget_remaining)
    if len(tuple(dict.fromkeys(evidence_refs))) > MAX_EVIDENCE_REFS:
        raise ValueError("too many evidence_refs")

    reasons: list[str] = []
    if not _same_scope(source_scope, target_scope):
        reasons.append("scope_mismatch")
    if trust < MIN_SOURCE_TRUST:
        reasons.append("source_trust_below_threshold")

    abuse_detected = requested > MAX_PRIMING_BOOST or requested > budget
    if abuse_detected:
        reasons.append("priming_request_capped")

    allowed = not any(reason in {"scope_mismatch", "source_trust_below_threshold"} for reason in reasons)
    boost = min(requested * trust, budget, MAX_PRIMING_BOOST) if allowed else 0.0
    return PrimingDecision(
        allowed=allowed,
        boost=boost,
        reasons=tuple(reasons),
        abuse_detected=abuse_detected,
        trace={
            "requested_boost": requested,
            "source_trust": trust,
            "budget_remaining": budget,
            "activation_cap": MAX_PRIMING_BOOST,
            "scope_isolated": _same_scope(source_scope, target_scope),
            "evidence_count": len(tuple(dict.fromkeys(evidence_refs))),
            "truth_mutated": False,
            "promotion_performed": False,
        },
    )
