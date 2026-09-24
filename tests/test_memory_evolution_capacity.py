from memory_permanent.memory_evolution_capacity_agent import (
    CapacitySnapshot,
    CapacityThresholds,
    EvolutionProof,
    MemoryEvolutionCapacityAgent,
)


def test_capacity_normal_warn_protect():
    a=MemoryEvolutionCapacityAgent(thresholds=CapacityThresholds())
    assert a.assess_capacity(CapacitySnapshot(1000,500,100)).state=='NORMAL'
    assert a.assess_capacity(CapacitySnapshot(1000,150,100)).state=='WARN'
    d=a.assess_capacity(CapacitySnapshot(1000,50,100))
    assert d.state=='PROTECT' and not d.allow_growth and not d.allow_nonessential_derivatives


def test_capacity_days_to_exhaustion_can_protect():
    a=MemoryEvolutionCapacityAgent()
    d=a.assess_capacity(CapacitySnapshot(1000,500,100,growth_bytes_per_day=100))
    assert d.state=='PROTECT' and 'CRITICAL_DAYS_TO_EXHAUSTION' in d.reasons


def test_evolution_requires_all_terminal_proofs():
    a=MemoryEvolutionCapacityAgent()
    base=dict(migration_version='0041',candidate_ref='abc',preflight_pass=True,backup_pass=True,isolated_apply_pass=True,regression_pass=True,retrieval_quality_status='PASS',restore_pass=True,integrity_pass=True,rollback_or_rollforward_ready=True)
    assert a.assess_evolution(EvolutionProof(**base)).allowed
    base['restore_pass']=False
    d=a.assess_evolution(EvolutionProof(**base))
    assert not d.allowed and 'RESTORE_FAILED' in d.reasons


def test_retrieval_quality_deny_blocks_evolution():
    a=MemoryEvolutionCapacityAgent()
    p=EvolutionProof('0041','abc',True,True,True,True,'DENY',True,True,True)
    d=a.assess_evolution(p)
    assert d.status=='DENY' and 'RETRIEVAL_QUALITY_DENY' in d.reasons
