from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

POLICY_VERSION = "LP-1.0.0"


@dataclass(frozen=True, slots=True)
class LearningDecision:
    policy_version: str
    computed_delta: float
    components: dict[str, float | int | str | bool]


class LearningPolicyEngine:
    """Deterministic, bounded and versioned outcome-to-confidence policy.

    The caller never supplies the resulting confidence delta. Inputs are outcome
    facts/evidence plus system-derived authority and prior version history.
    """

    SUCCESS_BASE = 0.04
    FAILURE_BASE = -0.06
    MAX_POSITIVE = 0.05
    MAX_NEGATIVE = -0.08

    @staticmethod
    def _numeric(value: Any) -> float | None:
        try:
            x = float(value)
        except (TypeError, ValueError):
            return None
        return x if math.isfinite(x) else None

    @classmethod
    def _sample_weight(cls, actual: dict[str, Any], evidence: dict[str, Any], authority_tier: str) -> float:
        raw = actual.get("sample_size", evidence.get("sample_size"))
        n = cls._numeric(raw)
        if n is None or n <= 0:
            return 0.8
        weight = min(1.0, 0.55 + math.log10(max(1.0, n)) * 0.15)
        if authority_tier == "AUTHENTICATED":
            weight = min(weight, 0.85)
        return round(weight, 6)

    @staticmethod
    def _evidence_weight(expected: dict[str, Any], actual: dict[str, Any], evidence: dict[str, Any], authority_tier: str) -> float:
        score = 0.5
        if expected and actual:
            score += 0.1
        proof_keys = {"proof_ref", "artifact_hash", "measurement_id", "evidence_ref", "trace_id"}
        if any(k in evidence for k in proof_keys):
            score += 0.15
        refs = evidence.get("independent_refs")
        if isinstance(refs, list) and refs:
            score += min(0.1, len(refs) * 0.025)
        if authority_tier == "ATTESTED":
            score += 0.05
        elif authority_tier == "INTERNAL":
            score += 0.025
        return round(min(0.9, max(0.4, score)), 6)

    @staticmethod
    def _authority_weight(authority_tier: str) -> float:
        return {"ATTESTED": 1.0, "INTERNAL": 0.9, "AUTHENTICATED": 0.75}.get(authority_tier, 0.65)

    @staticmethod
    def _repeatability_weight(success: bool, prior_successes: int, prior_failures: int) -> float:
        total = int(prior_successes) + int(prior_failures)
        if total <= 0:
            return 0.75
        matching = prior_successes if success else prior_failures
        ratio = matching / total
        history_bonus = min(0.15, total * 0.025)
        if ratio >= 0.75:
            return round(min(1.0, 0.82 + history_bonus), 6)
        if ratio <= 0.25:
            return 0.6
        return 0.75

    @staticmethod
    def _recency_weight(occurred_at: datetime, observed_at: datetime) -> float:
        occurred = occurred_at if occurred_at.tzinfo else occurred_at.replace(tzinfo=UTC)
        observed = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=UTC)
        delay_days = max(0.0, (observed - occurred).total_seconds() / 86400.0)
        if delay_days <= 1:
            return 1.0
        if delay_days <= 7:
            return 0.95
        if delay_days <= 30:
            return 0.85
        return 0.75

    @staticmethod
    def _independence_weight(evidence: dict[str, Any], authority_tier: str) -> float:
        refs = evidence.get("independent_refs")
        count = len(refs) if isinstance(refs, list) else 0
        if count >= 2 and authority_tier in {"ATTESTED", "INTERNAL"}:
            return 1.0
        if count >= 1:
            return 0.9 if authority_tier != "AUTHENTICATED" else 0.85
        return 0.8

    @staticmethod
    def _causality_weight(evidence: dict[str, Any], authority_tier: str) -> float:
        causal_ref = evidence.get("causal_proof_ref")
        if causal_ref and authority_tier in {"ATTESTED", "INTERNAL"}:
            return 1.0
        return 0.8

    def evaluate(
        self,
        *,
        success: bool,
        expected: dict[str, Any] | None,
        actual: dict[str, Any] | None,
        evidence: dict[str, Any] | None,
        authority_tier: str,
        prior_successes: int,
        prior_failures: int,
        occurred_at: datetime,
        observed_at: datetime,
    ) -> LearningDecision:
        expected = dict(expected or {})
        actual = dict(actual or {})
        evidence = dict(evidence or {})
        tier = str(authority_tier or "AUTHENTICATED").upper()
        if tier not in {"AUTHENTICATED", "ATTESTED", "INTERNAL"}:
            tier = "AUTHENTICATED"

        base = self.SUCCESS_BASE if success else self.FAILURE_BASE
        authority = self._authority_weight(tier)
        evidence_weight = self._evidence_weight(expected, actual, evidence, tier)
        repeatability = self._repeatability_weight(success, prior_successes, prior_failures)
        recency = self._recency_weight(occurred_at, observed_at)
        sample = self._sample_weight(actual, evidence, tier)
        independence = self._independence_weight(evidence, tier)
        causality = self._causality_weight(evidence, tier)

        raw = base * authority * evidence_weight * repeatability * recency * sample * independence * causality
        delta = min(self.MAX_POSITIVE, raw) if raw >= 0 else max(self.MAX_NEGATIVE, raw)
        delta = round(delta, 6)
        return LearningDecision(
            policy_version=POLICY_VERSION,
            computed_delta=delta,
            components={
                "base_delta": base,
                "authority_tier": tier,
                "authority_weight": authority,
                "evidence_weight": evidence_weight,
                "repeatability_weight": repeatability,
                "recency_weight": recency,
                "sample_weight": sample,
                "independence_weight": independence,
                "causality_weight": causality,
                "prior_successes": int(prior_successes),
                "prior_failures": int(prior_failures),
                "caller_delta_authoritative": False,
            },
        )
