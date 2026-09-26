from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .canonical_mutation import canonical_mutation_scope
from .consolidation_policy import (
    ConsolidationLimits,
    ConsolidationMode,
    SchedulerSignals,
    evaluate_schedule,
)
from .offline_consolidation import (
    OfflineCognitiveConsolidationEngine,
    PostgresConsolidationStore,
)

CONSOLIDATION_SCHEDULER_VERSION = "COS-1.0.0"


@dataclass(frozen=True, slots=True)
class ConsolidationSchedulerResult:
    status: str
    scope_key: str
    mode: str
    trigger: str
    run_id: str | None
    reasons: tuple[str, ...]
    recovered: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scope_key": self.scope_key,
            "mode": self.mode,
            "trigger": self.trigger,
            "run_id": self.run_id,
            "reasons": list(self.reasons),
            "recovered": self.recovered,
        }


def _lease_key(scope_key: str) -> str:
    normalized = str(scope_key).strip()
    if not normalized or len(normalized) > 512:
        raise ValueError("invalid consolidation scope_key")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]
    prefix = normalized[:160].replace(" ", "_")
    return f"cognitive-consolidation:{prefix}:{digest}"


class ConsolidationScheduler:
    """Portable one-shot scheduler policy; host schedulers invoke it instead of owning cognition."""

    def __init__(self, memory_store: Any, *, limits: ConsolidationLimits | None = None) -> None:
        self.memory_store = memory_store
        self.limits = limits or ConsolidationLimits()
        self.store = PostgresConsolidationStore(memory_store)
        self.engine = OfflineCognitiveConsolidationEngine(self.store, limits=self.limits)

    @property
    def actor_id(self) -> str:
        value = str(self.memory_store.access.agent_id or "").strip()
        if not value or value == "__SYSTEM__":
            raise PermissionError("dedicated consolidation agent identity required")
        return value

    def _acquire(self, scope_key: str) -> tuple[str, int]:
        key = _lease_key(scope_key)
        with canonical_mutation_scope(self.actor_id, "lease.acquire"):
            lease = self.memory_store.acquire_lease(key, ttl_seconds=self.limits.lease_ttl_seconds)
        return key, int(lease["fencing_token"])

    def _release(self, lease_key: str, fencing_token: int) -> None:
        with canonical_mutation_scope(self.actor_id, "lease.release"):
            self.memory_store.release_lease(lease_key, fencing_token=fencing_token)

    def run_once(
        self,
        *,
        scope_key: str,
        mode: ConsolidationMode,
        signals: SchedulerSignals,
        mission_id: str | None = None,
        session_id: str | None = None,
    ) -> ConsolidationSchedulerResult:
        decision = evaluate_schedule(mode, signals, limits=self.limits)
        if not decision.allowed:
            return ConsolidationSchedulerResult(
                status="SKIPPED",
                scope_key=scope_key,
                mode=mode.value,
                trigger=decision.trigger.value,
                run_id=None,
                reasons=decision.reasons,
            )
        lease_key, token = self._acquire(scope_key)
        try:
            result = self.engine.execute(
                scope_key=scope_key,
                mode=mode,
                trigger=decision.trigger,
                lease_key=lease_key,
                fencing_token=token,
                mission_id=mission_id,
                session_id=session_id,
            )
            return ConsolidationSchedulerResult(
                status=result.status,
                scope_key=scope_key,
                mode=mode.value,
                trigger=decision.trigger.value,
                run_id=result.run_id,
                reasons=(),
                recovered=result.recovered_from_interrupt,
            )
        finally:
            self._release(lease_key, token)

    def recover_run(self, run_id: str) -> ConsolidationSchedulerResult:
        run = self.store.load_run(run_id)
        if not run:
            raise KeyError(run_id)
        scope_key = str(run["scope_key"])
        lease_key, token = self._acquire(scope_key)
        try:
            result = self.engine.recover(run_id=run_id, lease_key=lease_key, fencing_token=token)
            return ConsolidationSchedulerResult(
                status=result.status,
                scope_key=scope_key,
                mode=result.mode,
                trigger=str(run["trigger_kind"]),
                run_id=result.run_id,
                reasons=(),
                recovered=True,
            )
        finally:
            self._release(lease_key, token)


def consolidation_scheduler_spec() -> dict[str, Any]:
    return {
        "version": CONSOLIDATION_SCHEDULER_VERSION,
        "host_coupled": False,
        "execution_model": "PORTABLE_ONE_SHOT_WORKER",
        "exclusive_scope_lease": True,
        "fencing_token_required": True,
        "default_enabled": False,
        "capture_retrieval_blocking": False,
        "supported_host_triggers": ["WINDOWS_TASK_SCHEDULER", "SYSTEMD_TIMER", "KUBERNETES_CRONJOB", "MANUAL"],
    }
