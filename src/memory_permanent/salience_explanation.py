from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True)
class SalienceExplanation:
    score: float
    top_dimensions: tuple[tuple[str, float], ...]
    evidence_limited: bool
    source_trust: float
    independent_evidence_count: int
    trace: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace", MappingProxyType(dict(self.trace)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "top_dimensions": [
                {"dimension": name, "value": value} for name, value in self.top_dimensions
            ],
            "evidence_limited": self.evidence_limited,
            "source_trust": self.source_trust,
            "independent_evidence_count": self.independent_evidence_count,
            "truth_mutated": False,
            "promotion_performed": False,
            **dict(self.trace),
        }


def explain_salience(
    *,
    score: float,
    dimensions: Mapping[str, float],
    evidence_limited: bool,
    source_trust: float,
    independent_evidence_count: int,
) -> SalienceExplanation:
    top = tuple(
        sorted(
            ((name, float(value)) for name, value in dimensions.items() if float(value) > 0.0),
            key=lambda item: (-item[1], item[0]),
        )[:5]
    )
    return SalienceExplanation(
        score=float(score),
        top_dimensions=top,
        evidence_limited=bool(evidence_limited),
        source_trust=float(source_trust),
        independent_evidence_count=int(independent_evidence_count),
        trace={"explanation_version": "SAL-EXPLAIN-1.0.0"},
    )
