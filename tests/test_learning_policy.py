from datetime import UTC, datetime, timedelta

from memory_permanent.learning_policy import POLICY_VERSION, LearningPolicyEngine


def test_caller_cannot_supply_delta_because_engine_computes_it():
    d=LearningPolicyEngine().evaluate(
        success=True, expected={'x':1}, actual={'x':1}, evidence={}, authority_tier='AUTHENTICATED',
        prior_successes=0, prior_failures=0, occurred_at=datetime.now(UTC), observed_at=datetime.now(UTC),
    )
    assert d.policy_version == POLICY_VERSION
    assert 0 < d.computed_delta <= 0.05
    assert d.components['caller_delta_authoritative'] is False


def test_failure_is_negative_and_bounded():
    d=LearningPolicyEngine().evaluate(
        success=False, expected={}, actual={}, evidence={}, authority_tier='AUTHENTICATED',
        prior_successes=3, prior_failures=0, occurred_at=datetime.now(UTC), observed_at=datetime.now(UTC),
    )
    assert -0.08 <= d.computed_delta < 0


def test_attested_evidence_can_weight_more_but_remains_bounded():
    now=datetime.now(UTC)
    low=LearningPolicyEngine().evaluate(
        success=True, expected={}, actual={}, evidence={}, authority_tier='AUTHENTICATED',
        prior_successes=0, prior_failures=0, occurred_at=now-timedelta(days=40), observed_at=now,
    )
    high=LearningPolicyEngine().evaluate(
        success=True, expected={'target':1}, actual={'target':1,'sample_size':1000},
        evidence={'proof_ref':'proof:1','independent_refs':['a','b'],'causal_proof_ref':'cause:1'}, authority_tier='ATTESTED',
        prior_successes=5, prior_failures=0, occurred_at=now, observed_at=now,
    )
    assert high.computed_delta > low.computed_delta
    assert high.computed_delta <= 0.05


def test_contradictory_history_reduces_repeatability_weight():
    now=datetime.now(UTC)
    d=LearningPolicyEngine().evaluate(
        success=True, expected={}, actual={}, evidence={}, authority_tier='AUTHENTICATED',
        prior_successes=0, prior_failures=5, occurred_at=now, observed_at=now,
    )
    assert d.components['repeatability_weight'] == 0.6
