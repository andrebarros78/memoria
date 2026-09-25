from __future__ import annotations

from dataclasses import dataclass

INTERFERENCE_POLICY_VERSION = "INT-1.0.0"
MAX_INTERFERENCE_PENALTY = 0.25
MAX_HABITUATION_PENALTY = 0.10


def _unit(name: str, value: float) -> float:
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


@dataclass(frozen=True, slots=True)
class InterferenceResult:
    interference_penalty: float
    habituation_penalty: float
    proactive_component: float
    retroactive_component: float
    contradiction_component: float
    policy_version: str = INTERFERENCE_POLICY_VERSION


def evaluate_interference(
    *,
    proactive_similarity: float = 0.0,
    retroactive_similarity: float = 0.0,
    contradiction_strength: float = 0.0,
    habituation_signal: float = 0.0,
) -> InterferenceResult:
    proactive = _unit("proactive_similarity", proactive_similarity) * 0.08
    retroactive = _unit("retroactive_similarity", retroactive_similarity) * 0.08
    contradiction = _unit("contradiction_strength", contradiction_strength) * 0.12
    habituation = min(_unit("habituation_signal", habituation_signal) * 0.10, MAX_HABITUATION_PENALTY)
    penalty = min(proactive + retroactive + contradiction, MAX_INTERFERENCE_PENALTY)
    return InterferenceResult(
        interference_penalty=penalty,
        habituation_penalty=habituation,
        proactive_component=proactive,
        retroactive_component=retroactive,
        contradiction_component=contradiction,
    )
