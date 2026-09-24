from __future__ import annotations

from datetime import UTC, datetime

import pytest

from memory_permanent.decision_memory import (
    DECISION_RECORD_VERSION,
    DecisionCriticality,
    build_replay_package,
    decision_core_material,
    sha256_json,
    validate_action,
    validate_decision_record,
)


def test_critical_decision_requires_multiple_alternatives_and_evidence() -> None:
    with pytest.raises(ValueError, match="two alternatives"):
        validate_decision_record(
            objective="Protect baseline",
            alternatives=[{"id":"a","label":"A"}],
            rationale="reason",
            action={"type":"RUN","target":"gate","parameters":{}},
            expected_outcome={"status":"PASS"},proof={"ticket":"p"},evidence_refs=[{"item_id":"m"}],
            criticality="CRITICAL",
        )
    with pytest.raises(ValueError, match="evidence"):
        validate_decision_record(
            objective="Protect baseline",
            alternatives=[{"id":"a","label":"A"},{"id":"b","label":"B"}],
            rationale="reason",
            action={"type":"RUN","target":"gate","parameters":{}},
            expected_outcome={"status":"PASS"},proof={"ticket":"p"},evidence_refs=[],
            criticality="CRITICAL",
        )


def test_action_is_structured_and_replayable() -> None:
    assert validate_action({"type":"RUN","target":"gate","parameters":{"mode":"safe"}})["parameters"]["mode"] == "safe"
    with pytest.raises(ValueError, match="type and target"):
        validate_action({"parameters":{}})
    with pytest.raises(ValueError, match="parameters"):
        validate_action({"type":"RUN","target":"gate","parameters":"unsafe"})


def test_decision_core_hash_is_deterministic() -> None:
    occurred=datetime(2026,9,2,12,0,tzinfo=UTC).isoformat()
    kwargs=dict(
        mission_id="mission-1",mission_anchor_type="SESSION",mission_anchor_id="mission-1",
        mission_snapshot={"objective":"x"},criticality="CRITICAL",objective="x",context={"k":1},
        alternatives=[{"id":"a","label":"A"},{"id":"b","label":"B"}],rationale="because",
        authority={"client_id":"local-admin"},action={"type":"RUN","target":"gate","parameters":{}},
        expected_outcome={"status":"PASS"},proof={"ref":"proof"},occurred_at=occurred,
    )
    a=decision_core_material(**kwargs)
    b=decision_core_material(**kwargs)
    assert sha256_json(a) == sha256_json(b)
    assert len(sha256_json(a)) == 64


def test_replay_hash_includes_actual_outcomes_and_is_snapshot_bound() -> None:
    decision={
        "decision_id":"dec-1","mission_id":"mission-1","mission_anchor_type":"SESSION","mission_anchor_id":"mission-1",
        "mission_snapshot":{"objective":"x"},"criticality":"CRITICAL","objective":"x","decision_context":{"k":1},
        "alternatives":[{"id":"a","label":"A"},{"id":"b","label":"B"}],"rationale":"because",
        "authority":{"client_id":"local-admin"},"action":{"type":"RUN","target":"gate","parameters":{}},
        "expected_outcome":{"status":"PASS"},"decision_proof":{"ref":"proof"},"core_sha256":"a"*64,
    }
    evidence=[{
        "role":"EVIDENCE","item_id":"mem-1","version_id":"ver-1","version_no":1,
        "content_sha256":"b"*64,"category_snapshot":"EVIDENCE","evidence_snapshot":{"content_text":"old"},
    }]
    outcomes=[{"decision_outcome_id":"dout-1","success":True,"actual_outcome":{"status":"PASS"},"proof":{"ref":"p"},"occurred_at":"2026-09-02T15:00:00+00:00","recorded_by":"local-admin"}]
    one=build_replay_package(decision,evidence,outcomes)
    two=build_replay_package(decision,evidence,outcomes)
    assert one == two
    assert one["record_version"] == DECISION_RECORD_VERSION == "DR-1.1.0"
    assert one["actual_outcomes"][0]["actual_outcome"] == {"status":"PASS"}
    assert len(one["replay_sha256"]) == 64
    changed=[{**evidence[0],"version_id":"ver-2"}]
    assert build_replay_package(decision,changed,outcomes)["replay_sha256"] != one["replay_sha256"]
    changed_outcomes=[{**outcomes[0],"actual_outcome":{"status":"FAIL"}}]
    assert build_replay_package(decision,evidence,changed_outcomes)["replay_sha256"] != one["replay_sha256"]


def test_decision_criticality_values_are_explicit() -> None:
    assert [x.value for x in DecisionCriticality] == ["NORMAL","HIGH","CRITICAL"]
