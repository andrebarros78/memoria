from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .canonical_mutation import CanonicalMutationService


@dataclass(frozen=True, slots=True)
class CapacityThresholds:
    warn_free_ratio: float = 0.20
    critical_free_ratio: float = 0.10
    warn_days_to_exhaustion: float = 30.0
    critical_days_to_exhaustion: float = 7.0
    def __post_init__(self) -> None:
        if not 0 <= self.critical_free_ratio < self.warn_free_ratio <= 1:
            raise ValueError('invalid free-space thresholds')
        if not 0 < self.critical_days_to_exhaustion < self.warn_days_to_exhaustion:
            raise ValueError('invalid exhaustion-day thresholds')

@dataclass(frozen=True, slots=True)
class CapacitySnapshot:
    filesystem_bytes: int
    free_bytes: int
    database_bytes: int
    wal_bytes: int = 0
    artifact_bytes: int = 0
    backup_bytes: int = 0
    growth_bytes_per_day: float = 0.0
    backlog_items: int = 0
    @property
    def free_ratio(self) -> float:
        return max(0.0,min(1.0,self.free_bytes/self.filesystem_bytes)) if self.filesystem_bytes > 0 else 0.0
    @property
    def days_to_exhaustion(self) -> float | None:
        if self.growth_bytes_per_day <= 0: return None
        return self.free_bytes/self.growth_bytes_per_day

@dataclass(frozen=True, slots=True)
class CapacityDecision:
    state: str
    allow_growth: bool
    allow_nonessential_derivatives: bool
    reasons: tuple[str,...]
    metrics: dict[str,Any]

@dataclass(frozen=True, slots=True)
class EvolutionProof:
    migration_version: str
    candidate_ref: str
    preflight_pass: bool
    backup_pass: bool
    isolated_apply_pass: bool
    regression_pass: bool
    retrieval_quality_status: str
    restore_pass: bool
    integrity_pass: bool
    rollback_or_rollforward_ready: bool

@dataclass(frozen=True, slots=True)
class EvolutionDecision:
    status: str
    reasons: tuple[str,...]
    proof: EvolutionProof
    @property
    def allowed(self) -> bool: return self.status == 'PASS'

class MemoryEvolutionCapacityAgent:
    def __init__(self, *, thresholds: CapacityThresholds | None = None, store: Any | None = None, actor_id: str='memory-evolution-capacity-agent') -> None:
        self.thresholds=thresholds or CapacityThresholds(); self.store=store; self.actor_id=actor_id
        self.mutations=CanonicalMutationService(store,actor_id=actor_id) if store is not None else None

    def assess_capacity(self, snapshot: CapacitySnapshot, *, persist: bool=False) -> CapacityDecision:
        t=self.thresholds; reasons=[]; state='NORMAL'
        days=snapshot.days_to_exhaustion
        if snapshot.filesystem_bytes <= 0:
            state='PROTECT'; reasons.append('INVALID_FILESYSTEM_CAPACITY')
        if snapshot.free_ratio <= t.critical_free_ratio:
            state='PROTECT'; reasons.append('CRITICAL_FREE_SPACE')
        elif snapshot.free_ratio <= t.warn_free_ratio and state != 'PROTECT':
            state='WARN'; reasons.append('LOW_FREE_SPACE')
        if days is not None and days <= t.critical_days_to_exhaustion:
            state='PROTECT'; reasons.append('CRITICAL_DAYS_TO_EXHAUSTION')
        elif days is not None and days <= t.warn_days_to_exhaustion and state == 'NORMAL':
            state='WARN'; reasons.append('LOW_DAYS_TO_EXHAUSTION')
        decision=CapacityDecision(state=state,allow_growth=state!='PROTECT',allow_nonessential_derivatives=state=='NORMAL',reasons=tuple(reasons),metrics={**asdict(snapshot),'free_ratio':snapshot.free_ratio,'days_to_exhaustion':days})
        if persist:
            if self.mutations is None: raise ValueError('persist=True requires store')
            store=self.store
            if store is None: raise ValueError('persist=True requires store')
            self.mutations.run_sanitized('capacity.snapshot',store.record_capacity_snapshot,metrics=decision.metrics,state=decision.state,reasons=list(decision.reasons),created_by=self.actor_id)
        return decision

    def assess_evolution(self, proof: EvolutionProof, *, persist: bool=False) -> EvolutionDecision:
        checks=(('PREFLIGHT_FAILED',proof.preflight_pass),('BACKUP_FAILED',proof.backup_pass),('ISOLATED_APPLY_FAILED',proof.isolated_apply_pass),('REGRESSION_FAILED',proof.regression_pass),('RETRIEVAL_QUALITY_DENY',str(proof.retrieval_quality_status).upper()=='PASS'),('RESTORE_FAILED',proof.restore_pass),('INTEGRITY_FAILED',proof.integrity_pass),('NO_ROLLBACK_OR_ROLLFORWARD',proof.rollback_or_rollforward_ready))
        reasons=tuple(reason for reason,ok in checks if not ok); decision=EvolutionDecision('PASS' if not reasons else 'DENY',reasons,proof)
        if persist:
            if self.mutations is None: raise ValueError('persist=True requires store')
            store=self.store
            if store is None: raise ValueError('persist=True requires store')
            self.mutations.run_sanitized('evolution.proof',store.record_evolution_proof,migration_version=proof.migration_version,candidate_ref=proof.candidate_ref,proof=asdict(proof),status=decision.status,reasons=list(decision.reasons),created_by=self.actor_id)
        return decision