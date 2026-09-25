from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

SALIENCE_POLICY_VERSION = "SAL-1.0.0"
SALIENCE_DIMENSIONS = (
    "novelty",
    "surprise",
    "risk",
    "reward",
    "loss",
    "urgency",
    "goal_relevance",
    "social_relevance",
    "operational_impact",
    "financial_impact",
    "safety_impact",
    "rarity",
    "irreversibility",
    "uncertainty",
)

_DIMENSION_WEIGHTS = MappingProxyType(
    {
        "novelty": 0.06,
        "surprise": 0.06,
        "risk": 0.10,
        "reward": 0.07,
        "loss": 0.08,
        "urgency": 0.10,
        "goal_relevance": 0.09,
        "social_relevance": 0.04,
        "operational_impact": 0.09,
        "financial_impact": 0.07,
        "safety_impact": 0.10,
        "rarity": 0.04,
        "irreversibility": 0.06,
        "uncertainty": 0.04,
    }
)


def _unit(name: str, value: float) -> float:
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


@dataclass(frozen=True, slots=True)
class SaliencePolicyDecision:
    score: float
    dimensions: Mapping[str, float]
    evidence_limited: bool
    source_trust: float
    independent_evidence_count: int
    policy_version: str = SALIENCE_POLICY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "dimensions", MappingProxyType(dict(self.dimensions)))


def evaluate_salience(
    dimensions: Mapping[str, float],
    *,
    source_trust: float,
    independent_evidence_count: int,
    consumer_final_score: float | None = None,
) -> SaliencePolicyDecision:
    if consumer_final_score is not None:
        raise ValueError("consumer-assigned final salience is forbidden")
    unknown = sorted(set(dimensions) - set(SALIENCE_DIMENSIONS))
    if unknown:
        raise ValueError(f"unknown salience dimensions: {','.join(unknown)}")
    normalized = {name: _unit(name, dimensions.get(name, 0.0)) for name in SALIENCE_DIMENSIONS}
    trust = _unit("source_trust", source_trust)
    evidence_count = int(independent_evidence_count)
    if evidence_count < 0:
        raise ValueError("independent_evidence_count must be non-negative")

    raw = sum(normalized[name] * _DIMENSION_WEIGHTS[name] for name in SALIENCE_DIMENSIONS)
    trust_factor = 0.50 + (0.50 * trust)
    score = raw * trust_factor

    high_impact = max(
        normalized["risk"],
        normalized["loss"],
        normalized["urgency"],
        normalized["operational_impact"],
        normalized["financial_impact"],
        normalized["safety_impact"],
        normalized["irreversibility"],
    )
    evidence_limited = high_impact >= 0.75 and evidence_count < 2
    if evidence_limited:
        score = min(score, 0.60)
    return SaliencePolicyDecision(
        score=min(max(score, 0.0), 1.0),
        dimensions=normalized,
        evidence_limited=evidence_limited,
        source_trust=trust,
        independent_evidence_count=evidence_count,
    )
