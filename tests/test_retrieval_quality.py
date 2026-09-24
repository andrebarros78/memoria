from memory_permanent.retrieval_quality import (
    RetrievalGoldenCase,
    RetrievalQualityAgent,
    RetrievalQualityThresholds,
)


class Result:
    def __init__(self, selected, trace_id="trace-rq", modes=("LEXICAL",)):
        self.selected=tuple(selected); self.trace_id=trace_id; self.retrieval_modes=tuple(modes); self.conflicts=()
class Engine:
    def __init__(self, rows): self.rows=rows
    def retrieve(self, query, **kwargs): return Result(self.rows.get(query, []), trace_id=f"trace-{query}")
def item(item_id, scope="GLOBAL_USER", ref=None): return {"item_id":item_id,"memory_scope":scope,"memory_scope_ref":ref}

def test_quality_agent_passes_exact_expected_results():
    run=RetrievalQualityAgent(Engine({"q":[item("a"),item("b")]})).evaluate([RetrievalGoldenCase("c1","q",("N",),frozenset({"a","b"}))])
    assert run.status=="PASS" and run.metrics["precision"]==1.0 and run.metrics["recall"]==1.0

def test_quality_agent_denies_forbidden_memory_leak():
    case=RetrievalGoldenCase("c1","q",("N",),frozenset({"a"}),frozenset({"secret"}))
    run=RetrievalQualityAgent(Engine({"q":[item("a"),item("secret")]})).evaluate([case])
    assert run.status=="DENY" and "FORBIDDEN_MEMORY_LEAK" in run.reasons

def test_quality_agent_denies_scope_isolation_violation():
    case=RetrievalGoldenCase("c1","q",("N",),frozenset({"a"}),allowed_scopes=(("GLOBAL_USER",None),("PROJECT","project-a")))
    run=RetrievalQualityAgent(Engine({"q":[item("a","PROJECT","other-project")]})).evaluate([case])
    assert run.status=="DENY" and "SCOPE_ISOLATION_VIOLATION" in run.reasons

def test_quality_agent_denies_empty_golden_set_fail_closed():
    run=RetrievalQualityAgent(Engine({})).evaluate([])
    assert run.status=="DENY" and run.reasons==("EMPTY_GOLDEN_SET",)

def test_quality_agent_denies_recall_regression():
    case=RetrievalGoldenCase("c1","q",("N",),frozenset({"a","b","c"}))
    run=RetrievalQualityAgent(Engine({"q":[item("a")]})).evaluate([case],thresholds=RetrievalQualityThresholds(min_precision=.5,min_recall=.8))
    assert run.status=="DENY" and "RECALL_BELOW_THRESHOLD" in run.reasons

def test_quality_agent_rejects_invalid_case_overlap():
    try: RetrievalGoldenCase("c1","q",("N",),frozenset({"a"}),frozenset({"a"}))
    except ValueError as exc: assert "both expected and forbidden" in str(exc)
    else: raise AssertionError("expected ValueError")

def test_quality_thresholds_are_bounded():
    try: RetrievalQualityThresholds(min_precision=1.1)
    except ValueError as exc: assert "between 0 and 1" in str(exc)
    else: raise AssertionError("expected ValueError")

def test_quality_persistence_requires_store_and_golden_set():
    agent=RetrievalQualityAgent(Engine({"q":[item("a")]})); case=RetrievalGoldenCase("c1","q",("N",),frozenset({"a"}))
    try: agent.evaluate([case],persist=True,golden_set_id="gs")
    except ValueError as exc: assert "requires store" in str(exc)
    else: raise AssertionError("expected ValueError")

def test_quality_agent_denies_temporal_violation():
    case=RetrievalGoldenCase('c1','q',('N',),expected_item_ids=frozenset({'current'}),temporal_forbidden_item_ids=frozenset({'stale'}))
    run=RetrievalQualityAgent(Engine({'q':[item('current'),item('stale')]})).evaluate([case])
    assert run.status=='DENY' and 'TEMPORAL_VIOLATION' in run.reasons
    assert run.metrics['temporal_violation_rate']==1.0


def test_quality_agent_denies_authority_violation():
    row=item('a'); row['provenance']={'authority':'UNTRUSTED'}
    case=RetrievalGoldenCase('c1','q',('N',),expected_item_ids=frozenset({'a'}),allowed_authorities=frozenset({'TRUSTED'}))
    run=RetrievalQualityAgent(Engine({'q':[row]})).evaluate([case])
    assert run.status=='DENY' and 'AUTHORITY_VIOLATION' in run.reasons
    assert run.metrics['authority_violation_rate']==1.0


def test_quality_agent_supports_memory_gateway_contract():
    class Gateway:
        def retrieve_context(self, query, **kwargs): return Result([item('a')], trace_id='trace-gateway')
    run=RetrievalQualityAgent(Gateway()).evaluate([RetrievalGoldenCase('c1','q',('N',),expected_item_ids=frozenset({'a'}))])
    assert run.status=='PASS' and run.cases[0].trace_id=='trace-gateway'


def test_quality_store_mutators_fail_closed_without_canonical_context():
    import pytest

    from memory_permanent.canonical_mutation import CanonicalMutationRequired
    from memory_permanent.store import PostgresMemoryStore
    store=object.__new__(PostgresMemoryStore)
    with pytest.raises(CanonicalMutationRequired):
        store.create_retrieval_golden_set(name='g',version=1,cases=[{'case_id':'c','query':'q','namespaces':['N']}],created_by='bypass')
    with pytest.raises(CanonicalMutationRequired):
        store.record_retrieval_quality_run(golden_set_id='g',candidate_ref='c',baseline_ref=None,thresholds={},metrics={},status='PASS',reasons=[],case_results=[],created_by='bypass')