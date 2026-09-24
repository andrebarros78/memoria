from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .cognitive_contracts import (
    CognitiveDecision,
    CognitiveEnvelope,
    CognitiveEvaluation,
    CognitiveMode,
)

COGNITIVE_POLICY_VERSION = "CKP-1.0.0"


@dataclass(frozen=True, slots=True)
class CognitivePolicyContext:
    authenticated_tenant_id: str
    authenticated_owner_id: str
    capability: str = "cognition:observe"


def evaluate_cognitive_envelope(envelope: CognitiveEnvelope, context: CognitivePolicyContext) -> CognitiveEvaluation:
    reasons: list[str] = []
    if envelope.scope.tenant_id != context.authenticated_tenant_id:
        reasons.append("tenant_scope_mismatch")
    if envelope.scope.owner_id != context.authenticated_owner_id:
        reasons.append("owner_scope_mismatch")
    if context.capability not in {"cognition:observe", "cognition:suggest"}:
        reasons.append("capability_denied")
    if envelope.mode is not CognitiveMode.SHADOW:
        reasons.append("f01_requires_shadow_mode")
    accepted = not reasons
    return CognitiveEvaluation(
        contract_version=COGNITIVE_POLICY_VERSION,
        decision=CognitiveDecision.OBSERVE if accepted else CognitiveDecision.REJECT,
        accepted=accepted,
        reasons=tuple(reasons),
        trace={
            "signal_type": envelope.signal_type.value,
            "source_ref": envelope.source_ref,
            "mode": envelope.mode.value,
            "tenant_bound": envelope.scope.tenant_id == context.authenticated_tenant_id,
            "owner_bound": envelope.scope.owner_id == context.authenticated_owner_id,
            "truth_mutated": False,
            "promotion_performed": False,
        },
    )


def cognitive_policy_spec() -> dict[str, Any]:
    return {
        "version": COGNITIVE_POLICY_VERSION,
        "phase": "F01_COGNITIVE_KERNEL_CONTRACTS",
        "behavior_change": False,
        "allowed_modes": [CognitiveMode.SHADOW.value],
        "allowed_capabilities": ["cognition:observe", "cognition:suggest"],
        "fail_closed_on_scope_mismatch": True,
        "direct_mutation": False,
        "direct_promotion": False,
    }
