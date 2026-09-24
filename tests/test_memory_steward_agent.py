import hashlib

import pytest

from memory_permanent.memory_steward_agent import (
    LearningObservation,
    MemoryStewardAgent,
)


def test_memory_steward_derives_procedure_only_from_measured_improvement():
    steward=MemoryStewardAgent(minimum_improvement=0.05)
    obs=LearningObservation('exp-1','Recover MCP quoting',0.55,0.92,('detect parser contract','place target before delimiter','replay'),('ev-1','ev-2'))
    p=steward.derive_procedure(obs)
    assert p.procedure_id.startswith('procedure-')
    assert len(p.sha256)==64
    assert p.source_experience_id=='exp-1'
    bad=LearningObservation('exp-2','No gain',0.9,0.91,('noop',),('ev',))
    with pytest.raises(ValueError): steward.derive_procedure(bad)


def test_memory_steward_activation_is_fail_closed():
    s=MemoryStewardAgent()
    digest=hashlib.sha256(b'impl').hexdigest()
    ok=s.activation_decision(operational_status='PROVEN',evaluation_passed=True,policy_allowed=True,implementation_sha256=digest,proof_types_passed=['REPLAY','RECOVERY'])
    assert ok.allow is True
    denied=s.activation_decision(operational_status='UNPROVEN',evaluation_passed=True,policy_allowed=True,implementation_sha256=digest,proof_types_passed=['REPLAY'])
    assert denied.allow is False
    assert any('RECOVERY' in x for x in denied.reasons)


def test_memory_steward_measures_reuse_improvement():
    result=MemoryStewardAgent.measure_reuse(baseline_score=0.55,reused_score=0.92)
    assert result['improved'] is True
    assert result['absolute_improvement'] == pytest.approx(0.37)
