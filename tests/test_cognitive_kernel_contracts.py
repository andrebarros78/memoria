from datetime import UTC, datetime
from types import MappingProxyType

import pytest

from memory_permanent.cognitive_contracts import (
    CognitiveEnvelope,
    CognitiveEventType,
    CognitiveFeature,
    CognitiveMode,
    CognitiveOperation,
    CognitiveScope,
    CognitiveSignalType,
    cognitive_contract_spec,
    default_cognitive_feature_flags,
)
from memory_permanent.cognitive_policy import (
    CognitivePolicyContext,
    cognitive_policy_spec,
    evaluate_cognitive_envelope,
)
from memory_permanent.cognitive_types import (
    BoundedScore,
    CapabilityClass,
    CognitiveRelation,
    CognitiveState,
    HumanAutomationLevel,
)


def _envelope(**kwargs):
    return CognitiveEnvelope(
        signal_type=kwargs.pop("signal_type", CognitiveSignalType.ACTIVATION),
        scope=kwargs.pop("scope", CognitiveScope(tenant_id="t1", owner_id="u1", project_id="p1")),
        source_ref=kwargs.pop("source_ref", "memory:m1"),
        evidence_refs=kwargs.pop("evidence_refs", ("e1", "e1", "e2")),
        occurred_at=kwargs.pop("occurred_at", datetime.now(UTC)),
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
    assert result.trace["feature_flags_enabled"] == ()


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
        _envelope(occurred_at=datetime.now())


def test_f01_types_are_bounded_and_canonical():
    assert BoundedScore(0.5).value == 0.5
    with pytest.raises(ValueError):
        BoundedScore(1.1)
    assert CognitiveState.SHADOW.value == "SHADOW"
    assert CognitiveRelation.CONTRADICTION.value == "CONTRADICTION"
    assert HumanAutomationLevel.HUMAN_APPROVAL_REQUIRED.value == "HUMAN_APPROVAL_REQUIRED"
    assert CapabilityClass.OPTIONAL_SYNC.value == "OPTIONAL_SYNC"


def test_f01_policy_spec_declares_no_behavior_change():
    spec = cognitive_policy_spec()
    assert spec["phase"] == "F01_COGNITIVE_KERNEL_CONTRACTS"
    assert spec["behavior_change"] is False
    assert spec["direct_mutation"] is False
    assert spec["feature_flags_default_off"] is True


def test_f01_all_cognitive_feature_flags_default_off():
    flags = default_cognitive_feature_flags()
    assert isinstance(flags, MappingProxyType)
    assert set(flags) == {feature.value for feature in CognitiveFeature}
    assert all(value is False for value in flags.values())


def test_f01_operations_events_and_ports_are_contract_only():
    spec = cognitive_contract_spec()
    assert CognitiveOperation.ACTIVATE.value in spec["proposed_operations"]
    assert CognitiveOperation.METACOGNITION.value in spec["proposed_operations"]
    assert CognitiveEventType.MEMORY_ACTIVATED.value in spec["event_types"]
    assert CognitiveEventType.INTENTION_TRIGGERED.value in spec["event_types"]
    assert "ActivationStorePort" in spec["storage_ports"]


def test_f01_scope_is_normalized_and_control_characters_fail_closed():
    scope = CognitiveScope(" tenant ", " owner ", project_id=" project ")
    assert (scope.tenant_id, scope.owner_id, scope.project_id) == ("tenant", "owner", "project")
    with pytest.raises(ValueError):
        CognitiveScope("tenant\nother", "owner")


def test_f01_contract_bounds_and_freezes_untrusted_metadata():
    envelope = _envelope(attributes={"safe": "value"})
    assert isinstance(envelope.attributes, MappingProxyType)
    with pytest.raises(TypeError):
        envelope.attributes["other"] = "value"
    with pytest.raises(ValueError):
        _envelope(evidence_refs=tuple(f"e{i}" for i in range(65)))
    with pytest.raises(ValueError):
        _envelope(attributes={str(i): i for i in range(65)})


def test_f01_trace_is_immutable():
    result = evaluate_cognitive_envelope(_envelope(), CognitivePolicyContext("t1", "u1"))
    assert isinstance(result.trace, MappingProxyType)
    with pytest.raises(TypeError):
        result.trace["truth_mutated"] = True
