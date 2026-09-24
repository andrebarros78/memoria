from datetime import UTC, datetime

import pytest

from memory_permanent.decision_memory import (
    DECISION_RECORD_VERSION,
    DecisionCriticality,
    build_replay_package,
    sha256_json,
    validate_decision_record,
)


def valid_record(criticality="CRITICAL"):
    return validate_decision_record(
        objective="Preserve sovereign continuity",
        alternatives=[{"id":"a","label":"A"},{"id":"b","label":"B"}],
        rationale="Evidence-backed choice",
        action={"type":"APPLY","target":"memory-core","parameters":{}},
        expected_outcome={"state":"stable"},
        proof={"kind":"test"},
        evidence_refs=[{"item_id":"mem-1","version_id":"ver-1","role":"EVIDENCE"}],
        criticality=criticality,
    )


def test_decision_record_version_is_1_1_0():
    assert DECISION_RECORD_VERSION == "DR-1.1.0"


def test_critical_decision_requires_two_alternatives():
    with pytest.raises(ValueError, match="at least two alternatives"):
        validate_decision_record(
            objective="x", alternatives=[{"id":"a","label":"A"}], rationale="r",
            action={"type":"APPLY","target":"x","parameters":{}}, expected_outcome={"ok":True},
            proof={"p":1}, evidence_refs=[{"item_id":"mem-1"}], criticality="CRITICAL",
        )


def test_critical_decision_requires_evidence():
    with pytest.raises(ValueError, match="evidence reference"):
        validate_decision_record(
            objective="x", alternatives=[{"id":"a","label":"A"},{"id":"b","label":"B"}], rationale="r",
            action={"type":"APPLY","target":"x","parameters":{}}, expected_outcome={"ok":True},
            proof={"p":1}, evidence_refs=[], criticality="CRITICAL",
        )


def test_replay_hash_is_deterministic_and_binds_actual_outcomes():
    decision={
        "decision_id":"dec-1","mission_id":"mission-1","mission_anchor_type":"CHECKPOINT","mission_anchor_id":"cp-1",
        "mission_snapshot":{"checkpoint_id":"cp-1"},"criticality":"CRITICAL","objective":"obj","decision_context":{"x":1},
        "alternatives":[{"id":"a","label":"A"},{"id":"b","label":"B"}],"rationale":"why","authority":{"client_id":"c"},
        "action":{"type":"APPLY","target":"x","parameters":{}},"expected_outcome":{"ok":True},"decision_proof":{"proof":"p"},
        "core_sha256":"a"*64,
    }
    evidence=[{"role":"EVIDENCE","item_id":"mem-1","version_id":"ver-1","version_no":1,"content_sha256":"b"*64,"category_snapshot":"EVIDENCE","evidence_snapshot":{"x":1}}]
    outcomes=[{"decision_outcome_id":"dout-1","success":True,"actual_outcome":{"ok":True},"proof":{"p":1},"occurred_at":datetime(2026,1,1,tzinfo=UTC).isoformat(),"recorded_by":"c"}]
    p1=build_replay_package(decision,evidence,outcomes)
    p2=build_replay_package(decision,evidence,outcomes)
    assert p1 == p2
    assert p1["actual_outcomes"][0]["actual_outcome"] == {"ok": True}
    changed=build_replay_package(decision,evidence,[{**outcomes[0],"actual_outcome":{"ok":False}}])
    assert p1["replay_sha256"] != changed["replay_sha256"]
    material={k:v for k,v in p1.items() if k!="replay_sha256"}
    assert p1["replay_sha256"] == sha256_json(material)


def test_normal_decision_allows_one_alternative_without_evidence():
    out=validate_decision_record(
        objective="x", alternatives=[{"id":"a","label":"A"}], rationale="r",
        action={"type":"APPLY","target":"x","parameters":{}}, expected_outcome={"ok":True},
        proof={"p":1}, evidence_refs=[], criticality=DecisionCriticality.NORMAL,
    )
    assert out["criticality"] == "NORMAL"
