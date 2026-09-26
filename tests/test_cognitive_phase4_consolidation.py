from __future__ import annotations

import pytest

from memory_permanent.consolidation_policy import (
    ConsolidationCandidateStatus,
    ConsolidationLimits,
    ConsolidationMode,
    SchedulerSignals,
    consolidation_policy_spec,
    evaluate_schedule,
    validate_candidate,
)
from memory_permanent.consolidation_replay import (
    ConsolidationSourceSnapshot,
    build_replay,
    replay_matches,
)
from memory_permanent.offline_consolidation import offline_consolidation_spec


def _source(memory_id: str, *, conflict: bool = False) -> ConsolidationSourceSnapshot:
    return ConsolidationSourceSnapshot(
        memory_id=memory_id,
        namespace="TEST",
        category="FACT",
        content_sha256=(memory_id[-1] if memory_id[-1] in "0123456789abcdef" else "a") * 64,
        confidence=0.8,
        salience=0.7,
        activation=0.6,
        outcome_signal=0.5,
        association_signal=0.4,
        conflict=conflict,
    )


def test_phase4_policy_is_optional_async_shadow_and_bounded():
    spec = consolidation_policy_spec()
    assert spec["capability_class"] == "OPTIONAL_ASYNC"
    assert spec["mode"] == "SHADOW"
    assert spec["truth_mutation_allowed"] is False
    assert spec["direct_promotion_allowed"] is False
    assert spec["candidate_state_required"] is True
    assert spec["proof_requirement"] is True
    assert spec["conflict_analysis"] is True
    assert spec["limits"]["min_sample"] >= 2
    assert spec["limits"]["max_run_ms"] <= 60_000


def test_phase4_idle_schedule_fails_closed_when_runtime_not_safe():
    denied = evaluate_schedule(
        ConsolidationMode.IDLE_CONSOLIDATION,
        SchedulerSignals(
            system_idle=False,
            queue_healthy=True,
            database_healthy=True,
            recovery_in_progress=False,
            io_budget_available=True,
            cpu_percent=10,
            unconsolidated_salience=0.8,
        ),
    )
    assert denied.allowed is False
    assert "system_not_idle" in denied.reasons

    denied_recovery = evaluate_schedule(
        ConsolidationMode.IDLE_CONSOLIDATION,
        SchedulerSignals(
            system_idle=True,
            queue_healthy=True,
            database_healthy=True,
            recovery_in_progress=True,
            io_budget_available=True,
            cpu_percent=10,
            unconsolidated_salience=0.8,
        ),
    )
    assert denied_recovery.allowed is False
    assert "recovery_in_progress" in denied_recovery.reasons


def test_phase4_idle_schedule_allows_only_healthy_idle_window():
    decision = evaluate_schedule(
        ConsolidationMode.IDLE_CONSOLIDATION,
        SchedulerSignals(
            system_idle=True,
            queue_healthy=True,
            database_healthy=True,
            recovery_in_progress=False,
            io_budget_available=True,
            cpu_percent=20,
            unconsolidated_salience=0.8,
        ),
    )
    assert decision.allowed is True
    assert decision.trigger.value == "IDLE"
    assert decision.trace["truth_mutated"] is False


def test_phase4_false_consolidation_guards_require_sample_proof_confidence_and_no_conflict():
    status, reasons = validate_candidate(sample_count=1, confidence=0.9, conflict=False, proof_count=1)
    assert status is ConsolidationCandidateStatus.REJECTED
    assert "minimum_sample_not_met" in reasons

    status, reasons = validate_candidate(sample_count=3, confidence=0.9, conflict=False, proof_count=1)
    assert status is ConsolidationCandidateStatus.REJECTED
    assert "proof_requirement_not_met" in reasons

    status, reasons = validate_candidate(sample_count=3, confidence=0.9, conflict=True, proof_count=3)
    assert status is ConsolidationCandidateStatus.REJECTED
    assert "conflict_requires_rejection" in reasons

    status, reasons = validate_candidate(sample_count=3, confidence=0.9, conflict=False, proof_count=3)
    assert status is ConsolidationCandidateStatus.VALIDATED_SHADOW
    assert reasons == ()


def test_phase4_replay_is_deterministic_and_contains_no_memory_content():
    sources = (_source("mem-a"), _source("mem-b"))
    forward = build_replay(sources)
    reverse = build_replay(tuple(reversed(sources)))
    assert forward.source_digest == reverse.source_digest
    assert forward.replay_digest == reverse.replay_digest
    assert forward.trace["contains_memory_content"] is False
    assert replay_matches(
        sources,
        expected_source_digest=forward.source_digest,
        expected_replay_digest=forward.replay_digest,
    )


def test_phase4_limits_reject_unbounded_configuration():
    with pytest.raises(ValueError):
        ConsolidationLimits(min_sample=1)
    with pytest.raises(ValueError):
        ConsolidationLimits(max_sources=513)
    with pytest.raises(ValueError):
        ConsolidationLimits(max_candidates=129)
    with pytest.raises(ValueError):
        ConsolidationLimits(max_cpu_percent=100)


def test_phase4_engine_contract_never_blocks_core_or_promotes_truth():
    spec = offline_consolidation_spec()
    assert spec["capture_retrieval_dependency"] is False
    assert spec["canonical_truth_mutation"] is False
    assert spec["candidate_only"] is True
    assert spec["replayable"] is True
    assert spec["checkpointed"] is True
    assert spec["recoverable_after_interruption"] is True
    assert spec["pipeline"] == [
        "SELECT",
        "REPLAY",
        "COMPARE",
        "CLUSTER",
        "ASSOCIATE",
        "DETECT_PATTERN",
        "GENERATE_CANDIDATE",
        "VALIDATE",
        "CONSOLIDATE",
        "RECORD_PROVENANCE",
    ]
