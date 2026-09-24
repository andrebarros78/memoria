from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class LearningObservation:
    experience_id: str
    title: str
    before_score: float
    after_score: float
    steps: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    @property
    def improvement(self) -> float:
        return float(self.after_score) - float(self.before_score)


@dataclass(frozen=True, slots=True)
class ProcedureArtifact:
    procedure_id: str
    title: str
    version: str
    steps: tuple[str, ...]
    source_experience_id: str
    evidence_refs: tuple[str, ...]
    sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "procedure_id": self.procedure_id,
            "title": self.title,
            "version": self.version,
            "steps": list(self.steps),
            "source_experience_id": self.source_experience_id,
            "evidence_refs": list(self.evidence_refs),
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ActivationDecision:
    allow: bool
    reasons: tuple[str, ...]


class MemoryStewardAgent:
    """Governance layer for turning measured experience into reusable procedures.

    This agent never talks to PostgreSQL directly. Persistence is performed by an
    injected signed API client/orchestrator after this deterministic policy gate.
    """

    def __init__(self, *, minimum_improvement: float = 0.01, minimum_evidence: int = 1) -> None:
        if minimum_improvement <= 0:
            raise ValueError("minimum_improvement must be > 0")
        if minimum_evidence < 1:
            raise ValueError("minimum_evidence must be >= 1")
        self.minimum_improvement = float(minimum_improvement)
        self.minimum_evidence = int(minimum_evidence)

    @staticmethod
    def _canonical_sha(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def derive_procedure(self, observation: LearningObservation, *, version: str = "1.0.0") -> ProcedureArtifact:
        if not observation.experience_id.strip():
            raise ValueError("experience_id is required")
        if not observation.title.strip():
            raise ValueError("title is required")
        if not observation.steps or any(not str(step).strip() for step in observation.steps):
            raise ValueError("at least one non-empty procedure step is required")
        if observation.improvement < self.minimum_improvement:
            raise ValueError("experience did not demonstrate enough improvement")
        if len(observation.evidence_refs) < self.minimum_evidence:
            raise ValueError("insufficient evidence to derive procedure")
        base: dict[str, Any] = {
            "title": observation.title.strip(),
            "version": version.strip(),
            "steps": [str(x).strip() for x in observation.steps],
            "source_experience_id": observation.experience_id.strip(),
            "evidence_refs": [str(x).strip() for x in observation.evidence_refs],
        }
        digest = self._canonical_sha(base)
        return ProcedureArtifact(
            procedure_id=f"procedure-{digest[:20]}",
            title=base["title"],
            version=base["version"],
            steps=tuple(base["steps"]),
            source_experience_id=base["source_experience_id"],
            evidence_refs=tuple(base["evidence_refs"]),
            sha256=digest,
        )

    def activation_decision(
        self,
        *,
        operational_status: str,
        evaluation_passed: bool,
        policy_allowed: bool,
        implementation_sha256: str,
        proof_types_passed: Iterable[str],
    ) -> ActivationDecision:
        reasons: list[str] = []
        status = str(operational_status).strip().upper()
        proofs = {str(x).strip().upper() for x in proof_types_passed}
        if status != "PROVEN":
            reasons.append("skill version is not PROVEN")
        if not evaluation_passed:
            reasons.append("evaluation did not pass")
        if not policy_allowed:
            reasons.append("policy denied activation")
        if len(str(implementation_sha256)) != 64:
            reasons.append("implementation hash is invalid")
        for required in ("REPLAY", "RECOVERY"):
            if required not in proofs:
                reasons.append(f"missing {required} proof")
        return ActivationDecision(allow=not reasons, reasons=tuple(reasons))

    @staticmethod
    def measure_reuse(*, baseline_score: float, reused_score: float) -> dict[str, float | bool]:
        baseline = float(baseline_score)
        reused = float(reused_score)
        delta = reused - baseline
        relative = (delta / abs(baseline)) if baseline else (1.0 if delta > 0 else 0.0)
        return {
            "baseline_score": baseline,
            "reused_score": reused,
            "absolute_improvement": delta,
            "relative_improvement": relative,
            "improved": delta > 0,
        }
