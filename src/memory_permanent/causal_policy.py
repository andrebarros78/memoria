from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ontology import KnowledgeType

CAUSAL_POLICY_VERSION = "CP-1.0.0"
MIN_ATTRIBUTION_CONFIDENCE = 0.80
MIN_SAMPLE_SIZE = 30
MIN_REPETITION_COUNT = 2
MIN_INDEPENDENT_REFS = 2


@dataclass(frozen=True, slots=True)
class CausalDecision:
    policy_version: str
    eligible: bool
    criteria: dict[str, bool]
    failure_reasons: tuple[str, ...]


def _nonempty_mapping(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _independent_ref_count(evidence: dict[str, Any]) -> int:
    refs = evidence.get("independent_refs")
    if not isinstance(refs, list):
        return 0
    return len({str(x).strip() for x in refs if str(x).strip()})


def evaluate_causal_assessment(
    *,
    source_category: str | KnowledgeType,
    hypothesis: dict[str, Any],
    intervention: dict[str, Any],
    comparator: dict[str, Any],
    confounders: list[Any],
    confounder_control: dict[str, Any],
    mechanism: dict[str, Any],
    counterfactual: dict[str, Any],
    attribution_confidence: float,
    sample_size: int,
    repetition_count: int,
    evidence: dict[str, Any],
) -> CausalDecision:
    category = KnowledgeType(str(source_category).strip().upper())
    evidence = dict(evidence or {})
    confounder_control = dict(confounder_control or {})
    mechanism = dict(mechanism or {})
    counterfactual = dict(counterfactual or {})

    criteria = {
        "source_is_correlation": category is KnowledgeType.CORRELATION,
        "hypothesis_present": _nonempty_mapping(hypothesis),
        "intervention_present": _nonempty_mapping(intervention),
        "comparator_or_control_present": _nonempty_mapping(comparator),
        "confounders_explicit": isinstance(confounders, list),
        "confounders_addressed": _nonempty_mapping(confounder_control) and confounder_control.get("addressed") is True,
        "mechanism_supported": _nonempty_mapping(mechanism) and mechanism.get("supported") is True,
        "counterfactual_supported": _nonempty_mapping(counterfactual) and counterfactual.get("supported") is True,
        "attribution_confidence_sufficient": float(attribution_confidence) >= MIN_ATTRIBUTION_CONFIDENCE,
        "sample_size_sufficient": int(sample_size) >= MIN_SAMPLE_SIZE,
        "repetition_sufficient": int(repetition_count) >= MIN_REPETITION_COUNT,
        "independent_evidence_sufficient": _independent_ref_count(evidence) >= MIN_INDEPENDENT_REFS,
        "replications_consistent": evidence.get("replications_consistent") is True,
    }
    failures = tuple(name for name, passed in criteria.items() if not passed)
    return CausalDecision(
        policy_version=CAUSAL_POLICY_VERSION,
        eligible=not failures,
        criteria=criteria,
        failure_reasons=failures,
    )


def causal_policy_spec() -> dict[str, Any]:
    return {
        "version": CAUSAL_POLICY_VERSION,
        "promotion": "CORRELATION -> CAUSE",
        "direct_cause_creation_allowed": False,
        "generic_cause_transition_allowed": False,
        "thresholds": {
            "minimum_attribution_confidence": MIN_ATTRIBUTION_CONFIDENCE,
            "minimum_sample_size": MIN_SAMPLE_SIZE,
            "minimum_repetition_count": MIN_REPETITION_COUNT,
            "minimum_independent_evidence_refs": MIN_INDEPENDENT_REFS,
        },
        "required_evidence": [
            "hypothesis",
            "intervention",
            "comparator_or_control",
            "confounders",
            "confounder_control.addressed=true",
            "mechanism.supported=true",
            "counterfactual.supported=true",
            "attribution_confidence",
            "sample_size",
            "repetition_count",
            "evidence.independent_refs",
            "evidence.replications_consistent=true",
        ],
    }
