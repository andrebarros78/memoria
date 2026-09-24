from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .canonical_mutation import CanonicalMutationService


@dataclass(frozen=True, slots=True)
class RetrievalGoldenCase:
    case_id: str
    query: str
    namespaces: tuple[str, ...]
    expected_item_ids: frozenset[str] = field(default_factory=frozenset)
    forbidden_item_ids: frozenset[str] = field(default_factory=frozenset)
    temporal_forbidden_item_ids: frozenset[str] = field(default_factory=frozenset)
    allowed_scopes: tuple[tuple[str, str | None], ...] = ()
    allowed_authorities: frozenset[str] = field(default_factory=frozenset)
    mission_id: str | None = None
    session_id: str | None = None
    valid_at: datetime | None = None
    known_at: datetime | None = None
    limit: int = 8
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError('case_id required')
        if not self.query.strip():
            raise ValueError('query required')
        if not self.namespaces:
            raise ValueError('at least one namespace required')
        forbidden = self.forbidden_item_ids | self.temporal_forbidden_item_ids
        if self.expected_item_ids & forbidden:
            raise ValueError('an item cannot be both expected and forbidden')
        if self.limit < 1:
            raise ValueError('limit must be positive')


@dataclass(frozen=True, slots=True)
class RetrievalQualityThresholds:
    min_precision: float = 0.80
    min_recall: float = 0.80
    min_case_pass_rate: float = 1.0
    max_forbidden_hit_rate: float = 0.0
    max_scope_violation_rate: float = 0.0
    max_temporal_violation_rate: float = 0.0
    max_authority_violation_rate: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            'min_precision','min_recall','min_case_pass_rate','max_forbidden_hit_rate',
            'max_scope_violation_rate','max_temporal_violation_rate','max_authority_violation_rate',
        ):
            value=float(getattr(self,name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f'{name} must be between 0 and 1')

    def as_dict(self) -> dict[str,float]:
        return {name:float(getattr(self,name)) for name in (
            'min_precision','min_recall','min_case_pass_rate','max_forbidden_hit_rate',
            'max_scope_violation_rate','max_temporal_violation_rate','max_authority_violation_rate',
        )}


@dataclass(frozen=True, slots=True)
class RetrievalCaseResult:
    case_id: str
    trace_id: str
    selected_item_ids: tuple[str,...]
    precision: float
    recall: float
    forbidden_hits: tuple[str,...]
    temporal_violations: tuple[str,...]
    scope_violations: tuple[dict[str,Any],...]
    authority_violations: tuple[dict[str,Any],...]
    passed: bool
    details: dict[str,Any]

    def as_dict(self) -> dict[str,Any]:
        return {
            'case_id':self.case_id,'trace_id':self.trace_id,'selected_item_ids':list(self.selected_item_ids),
            'precision':self.precision,'recall':self.recall,'forbidden_hits':list(self.forbidden_hits),
            'temporal_violations':list(self.temporal_violations),'scope_violations':list(self.scope_violations),
            'authority_violations':list(self.authority_violations),'passed':self.passed,'details':self.details,
        }


@dataclass(frozen=True, slots=True)
class RetrievalQualityRun:
    status: str
    metrics: dict[str,float]
    reasons: tuple[str,...]
    cases: tuple[RetrievalCaseResult,...]
    persisted_run_id: str | None = None

    @property
    def allowed(self) -> bool:
        return self.status == 'PASS'


class RetrievalQualityAgent:
    """Fail-closed evaluator for sovereign retrieval golden sets."""

    def __init__(self, retrieval: Any, *, store: Any | None = None, actor_id: str = 'retrieval-quality-agent') -> None:
        self.retrieval=retrieval
        self.store=store
        self.actor_id=actor_id
        self.mutations=CanonicalMutationService(store,actor_id=actor_id) if store is not None else None

    def _retrieve(self, case: RetrievalGoldenCase) -> Any:
        kwargs=dict(namespaces=case.namespaces,limit=case.limit,mission_id=case.mission_id,session_id=case.session_id,valid_at=case.valid_at,known_at=case.known_at)
        if hasattr(self.retrieval,'retrieve_context'):
            return self.retrieval.retrieve_context(case.query,**kwargs)
        return self.retrieval.retrieve(case.query,**kwargs)

    @staticmethod
    def _scope_violations(selected: Iterable[dict[str,Any]], allowed: tuple[tuple[str,str|None],...]) -> tuple[dict[str,Any],...]:
        if not allowed:
            return ()
        normalized={(str(scope).upper(),None if ref is None else str(ref)) for scope,ref in allowed}
        violations=[]
        for item in selected:
            scope=str(item.get('memory_scope') or 'GLOBAL_USER').upper(); ref=item.get('memory_scope_ref')
            pair=(scope,None if ref is None else str(ref))
            if pair not in normalized:
                violations.append({'item_id':str(item.get('item_id') or ''),'memory_scope':scope,'memory_scope_ref':ref})
        return tuple(violations)

    @staticmethod
    def _authority(item: dict[str,Any]) -> str:
        provenance=item.get('provenance')
        if isinstance(provenance,dict):
            value=provenance.get('authority') or provenance.get('authority_class')
            if value:
                return str(value).upper()
        return str(item.get('source') or 'UNKNOWN').upper()

    @classmethod
    def _authority_violations(cls, selected: Iterable[dict[str,Any]], allowed: frozenset[str]) -> tuple[dict[str,Any],...]:
        if not allowed:
            return ()
        accepted={str(x).upper() for x in allowed}
        violations=[]
        for item in selected:
            authority=cls._authority(item)
            if authority not in accepted:
                violations.append({'item_id':str(item.get('item_id') or ''),'authority':authority})
        return tuple(violations)

    @staticmethod
    def _precision_recall(selected_ids: tuple[str,...], expected: frozenset[str]) -> tuple[float,float]:
        if not expected:
            return (1.0 if not selected_ids else 0.0,1.0)
        hits=len(set(selected_ids)&set(expected))
        return (hits/len(selected_ids) if selected_ids else 0.0,hits/len(expected))

    def evaluate_case(self, case: RetrievalGoldenCase, thresholds: RetrievalQualityThresholds) -> RetrievalCaseResult:
        result=self._retrieve(case)
        selected=tuple(result.selected)
        selected_ids=tuple(str(item.get('item_id') or '') for item in selected)
        precision,recall=self._precision_recall(selected_ids,case.expected_item_ids)
        forbidden_hits=tuple(sorted(set(selected_ids)&set(case.forbidden_item_ids)))
        temporal_violations=tuple(sorted(set(selected_ids)&set(case.temporal_forbidden_item_ids)))
        scope_violations=self._scope_violations(selected,case.allowed_scopes)
        authority_violations=self._authority_violations(selected,case.allowed_authorities)
        passed=(precision>=thresholds.min_precision and recall>=thresholds.min_recall and not forbidden_hits and not temporal_violations and not scope_violations and not authority_violations)
        return RetrievalCaseResult(
            case_id=case.case_id,trace_id=str(result.trace_id),selected_item_ids=selected_ids,precision=precision,recall=recall,
            forbidden_hits=forbidden_hits,temporal_violations=temporal_violations,scope_violations=scope_violations,
            authority_violations=authority_violations,passed=passed,
            details={'retrieval_modes':list(getattr(result,'retrieval_modes',()) or ()),'conflict_count':len(getattr(result,'conflicts',()) or ()),'expected_count':len(case.expected_item_ids),'selected_count':len(selected_ids)},
        )

    def evaluate(self, cases: Iterable[RetrievalGoldenCase], *, thresholds: RetrievalQualityThresholds | None = None, golden_set_id: str | None = None, candidate_ref: str = 'working-tree', baseline_ref: str | None = None, persist: bool = False) -> RetrievalQualityRun:
        policy=thresholds or RetrievalQualityThresholds(); case_list=tuple(cases)
        if not case_list:
            return RetrievalQualityRun(status='DENY',metrics={'precision':0.0,'recall':0.0,'case_pass_rate':0.0,'forbidden_hit_rate':0.0,'scope_violation_rate':0.0,'temporal_violation_rate':0.0,'authority_violation_rate':0.0},reasons=('EMPTY_GOLDEN_SET',),cases=())  # nosec B105 - numeric quality metric named pass_rate, not a credential
        results=tuple(self.evaluate_case(case,policy) for case in case_list); count=len(results)
        metrics={
            'precision':sum(x.precision for x in results)/count,'recall':sum(x.recall for x in results)/count,
            'case_pass_rate':sum(x.passed for x in results)/count,'forbidden_hit_rate':sum(bool(x.forbidden_hits) for x in results)/count,
            'scope_violation_rate':sum(bool(x.scope_violations) for x in results)/count,'temporal_violation_rate':sum(bool(x.temporal_violations) for x in results)/count,
            'authority_violation_rate':sum(bool(x.authority_violations) for x in results)/count,
        }
        reasons=[]
        if metrics['precision']<policy.min_precision: reasons.append('PRECISION_BELOW_THRESHOLD')
        if metrics['recall']<policy.min_recall: reasons.append('RECALL_BELOW_THRESHOLD')
        if metrics['case_pass_rate']<policy.min_case_pass_rate: reasons.append('CASE_PASS_RATE_BELOW_THRESHOLD')
        if metrics['forbidden_hit_rate']>policy.max_forbidden_hit_rate: reasons.append('FORBIDDEN_MEMORY_LEAK')
        if metrics['scope_violation_rate']>policy.max_scope_violation_rate: reasons.append('SCOPE_ISOLATION_VIOLATION')
        if metrics['temporal_violation_rate']>policy.max_temporal_violation_rate: reasons.append('TEMPORAL_VIOLATION')
        if metrics['authority_violation_rate']>policy.max_authority_violation_rate: reasons.append('AUTHORITY_VIOLATION')
        status='PASS' if not reasons else 'DENY'; persisted_run_id=None
        if persist:
            if self.mutations is None or not golden_set_id:
                raise ValueError('persist=True requires store and golden_set_id')
            store=self.store
            if store is None: raise ValueError('persist=True requires store and golden_set_id')
            payload=self.mutations.run_sanitized('retrieval.quality.run',store.record_retrieval_quality_run,golden_set_id=golden_set_id,candidate_ref=candidate_ref,baseline_ref=baseline_ref,thresholds=policy.as_dict(),metrics=metrics,status=status,reasons=reasons,case_results=[x.as_dict() for x in results],created_by=self.actor_id)
            persisted_run_id=str(payload['run_id'])
        return RetrievalQualityRun(status=status,metrics=metrics,reasons=tuple(reasons),cases=results,persisted_run_id=persisted_run_id)