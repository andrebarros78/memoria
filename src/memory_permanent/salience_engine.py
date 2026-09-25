from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .salience_explanation import SalienceExplanation, explain_salience
from .salience_policy import SALIENCE_POLICY_VERSION, evaluate_salience


@dataclass(frozen=True, slots=True)
class SalienceResult:
    score: float
    dimensions: Mapping[str, float]
    explanation: SalienceExplanation
    policy_version: str = SALIENCE_POLICY_VERSION
    mode: str = "SHADOW"

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimensions", MappingProxyType(dict(self.dimensions)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "dimensions": dict(self.dimensions),
            "explanation": self.explanation.as_dict(),
            "policy_version": self.policy_version,
            "mode": self.mode,
            "truth_mutated": False,
            "promotion_performed": False,
        }


class SalienceEngine:
    def compute(
        self,
        dimensions: Mapping[str, float],
        *,
        source_trust: float,
        independent_evidence_count: int,
        consumer_final_score: float | None = None,
    ) -> SalienceResult:
        decision = evaluate_salience(
            dimensions,
            source_trust=source_trust,
            independent_evidence_count=independent_evidence_count,
            consumer_final_score=consumer_final_score,
        )
        explanation = explain_salience(
            score=decision.score,
            dimensions=decision.dimensions,
            evidence_limited=decision.evidence_limited,
            source_trust=decision.source_trust,
            independent_evidence_count=decision.independent_evidence_count,
        )
        return SalienceResult(
            score=decision.score,
            dimensions=decision.dimensions,
            explanation=explanation,
        )
