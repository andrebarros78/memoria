from memory_permanent.causal_policy import (
    CAUSAL_POLICY_VERSION,
    causal_policy_spec,
    evaluate_causal_assessment,
)


def eligible_payload() -> dict:
    return {
        "source_category": "CORRELATION",
        "hypothesis": {"statement": "intervention changes outcome"},
        "intervention": {"description": "apply treatment"},
        "comparator": {"kind": "CONTROL", "description": "no treatment"},
        "confounders": [{"name": "seasonality"}],
        "confounder_control": {"addressed": True, "method": "stratification"},
        "mechanism": {"supported": True, "description": "measured pathway"},
        "counterfactual": {"supported": True, "description": "control estimates untreated state"},
        "attribution_confidence": 0.91,
        "sample_size": 120,
        "repetition_count": 3,
        "evidence": {
            "independent_refs": ["trial-a", "trial-b"],
            "replications_consistent": True,
        },
    }


def test_policy_spec_is_explicit_and_fail_closed() -> None:
    spec = causal_policy_spec()
    assert spec["version"] == CAUSAL_POLICY_VERSION == "CP-1.0.0"
    assert spec["promotion"] == "CORRELATION -> CAUSE"
    assert spec["direct_cause_creation_allowed"] is False
    assert spec["generic_cause_transition_allowed"] is False
    assert spec["thresholds"] == {
        "minimum_attribution_confidence": 0.8,
        "minimum_sample_size": 30,
        "minimum_repetition_count": 2,
        "minimum_independent_evidence_refs": 2,
    }


def test_complete_causal_assessment_is_eligible() -> None:
    decision = evaluate_causal_assessment(**eligible_payload())
    assert decision.eligible is True
    assert decision.failure_reasons == ()
    assert all(decision.criteria.values())


def test_success_like_evidence_alone_is_not_causal() -> None:
    payload = eligible_payload()
    payload.update(
        comparator={},
        confounder_control={"addressed": False},
        mechanism={"supported": False},
        counterfactual={"supported": False},
        attribution_confidence=0.99,
        sample_size=1,
        repetition_count=1,
        evidence={"success": True, "independent_refs": [], "replications_consistent": False},
    )
    decision = evaluate_causal_assessment(**payload)
    assert decision.eligible is False
    assert "comparator_or_control_present" in decision.failure_reasons
    assert "confounders_addressed" in decision.failure_reasons
    assert "mechanism_supported" in decision.failure_reasons
    assert "counterfactual_supported" in decision.failure_reasons
    assert "sample_size_sufficient" in decision.failure_reasons
    assert "repetition_sufficient" in decision.failure_reasons


def test_duplicate_evidence_refs_do_not_count_as_independent() -> None:
    payload = eligible_payload()
    payload["evidence"] = {"independent_refs": ["same", "same"], "replications_consistent": True}
    decision = evaluate_causal_assessment(**payload)
    assert decision.eligible is False
    assert decision.criteria["independent_evidence_sufficient"] is False


def test_only_correlation_can_be_promoted_to_cause() -> None:
    payload = eligible_payload()
    payload["source_category"] = "FACT"
    decision = evaluate_causal_assessment(**payload)
    assert decision.eligible is False
    assert decision.failure_reasons == ("source_is_correlation",)
