from datetime import UTC, datetime

import pytest

from memory_permanent.cognitive_contracts import (
    CognitiveEnvelope,
    CognitiveMode,
    CognitiveScope,
    CognitiveSignalType,
    cognitive_contract_spec,
)
from memory_permanent.cognitive_policy import (
    CognitivePolicyContext,
    cognitive_policy_spec,
    evaluate_cognitive_envelope,
)
from memory_permanent.cognitive_types import (
    BoundedScore,
    CognitiveRelation,
    CognitiveState,
)


def _envelope(**kwargs):
    return CognitiveEnvelope(
        signal_type=CognitiveSignalType.ACTIVATION,
        scope=kwargs.pop("scope", CognitiveScope(tenant_id="t1", owner_id="u1", project_id="p1")),
        source_ref="memory:m1",
        evidence_refs=("e1", "e1", "e2"),
        occurred_at=datetime.now(UTC),
        **kwargs,
    )


def test_f01_contract_is_shadow_fail_closed_and_non_mutating():
    spec = cognitive_contract_spec()
    assert spec["default_mode"] == "SHADOW"
    assert spec["mutation_authority"] == "NONE"
    assert spec["truth_mutation_allowed"] is False
    assert spec["direct_promotion_allowed"] is False
    assert spec["cross_scope_activation_allowed"] is False


def test_f01_policy_accepts_same_scope_observation_with_trace():
    result = evaluate_cognitive_envelope(_envelope(), CognitivePolicyContext("t1", "u1"))
    assert result.accepted is True
    assert result.trace["truth_mutated"] is False
    assert result.trace["promotion_performed"] is False


def test_f01_policy_rejects_cross_tenant_and_cross_owner():
    result = evaluate_cognitive_envelope(_envelope(), CognitivePolicyContext("other", "other"))
    assert result.accepted is False
    assert set(result.reasons) == {"tenant_scope_mismatch", "owner_scope_mismatch"}


def test_f01_policy_rejects_enabled_mode_until_later_gate():
    result = evaluate_cognitive_envelope(_envelope(mode=CognitiveMode.ENABLED), CognitivePolicyContext("t1", "u1"))
    assert result.accepted is False
    assert "f01_requires_shadow_mode" in result.reasons


def test_f01_policy_rejects_unauthorized_capability():
    result = evaluate_cognitive_envelope(_envelope(), CognitivePolicyContext("t1", "u1", capability="memory:write"))
    assert result.accepted is False
    assert result.reasons == ("capability_denied",)


def test_f01_contract_normalizes_evidence_and_requires_aware_time():
    assert _envelope().evidence_refs == ("e1", "e2")
    with pytest.raises(ValueError):
        CognitiveEnvelope(CognitiveSignalType.ACTIVATION, CognitiveScope("t1", "u1"), "m1", occurred_at=datetime.now())


def test_f01_types_are_bounded_and_canonical():
    assert BoundedScore(0.5).value == 0.5
    with pytest.raises(ValueError):
        BoundedScore(1.1)
    assert CognitiveState.SHADOW.value == "SHADOW"
    assert CognitiveRelation.CONTRADICTION.value == "CONTRADICTION"


def test_f01_policy_spec_declares_no_behavior_change():
    spec = cognitive_policy_spec()
    assert spec["phase"] == "F01_COGNITIVE_KERNEL_CONTRACTS"
    assert spec["behavior_change"] is False
    assert spec["direct_mutation"] is False
