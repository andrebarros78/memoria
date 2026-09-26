from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

CONSOLIDATION_POLICY_VERSION = "CON-1.0.0"


class ConsolidationMode(StrEnum):
    MICRO_CONSOLIDATION = "MICRO_CONSOLIDATION"
    IDLE_CONSOLIDATION = "IDLE_CONSOLIDATION"
    DAILY_CONSOLIDATION = "DAILY_CONSOLIDATION"
    DEEP_CONSOLIDATION = "DEEP_CONSOLIDATION"
    MANUAL_CONSOLIDATION = "MANUAL_CONSOLIDATION"
    RECOVERY_CONSOLIDATION = "RECOVERY_CONSOLIDATION"


class ConsolidationTrigger(StrEnum):
    IDLE = "IDLE"
    TIME_WINDOW = "TIME_WINDOW"
    EVENT_THRESHOLD = "EVENT_THRESHOLD"
    MEMORY_PRESSURE = "MEMORY_PRESSURE"
    MANUAL = "MANUAL"
    RECOVERY = "RECOVERY"


class ConsolidationCandidateStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    VALIDATED_SHADOW = "VALIDATED_SHADOW"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ConsolidationLimits:
    min_sample: int = 2
    max_sources: int = 64
    max_candidates: int = 32
    min_candidate_confidence: float = 0.55
    max_cpu_percent: float = 70.0
    max_run_ms: int = 5_000
    lease_ttl_seconds: int = 30

    def __post_init__(self) -> None:
        if not 2 <= int(self.min_sample) <= 16:
            raise ValueError("min_sample out of bounds")
        if not 2 <= int(self.max_sources) <= 512:
            raise ValueError("max_sources out of bounds")
        if not 1 <= int(self.max_candidates) <= 128:
            raise ValueError("max_candidates out of bounds")
        if not 0.0 <= float(self.min_candidate_confidence) <= 1.0:
            raise ValueError("min_candidate_confidence out of bounds")
        if not 1.0 <= float(self.max_cpu_percent) <= 95.0:
            raise ValueError("max_cpu_percent out of bounds")
        if not 100 <= int(self.max_run_ms) <= 60_000:
            raise ValueError("max_run_ms out of bounds")
        if not 5 <= int(self.lease_ttl_seconds) <= 3600:
            raise ValueError("lease_ttl_seconds out of bounds")


@dataclass(frozen=True, slots=True)
class SchedulerSignals:
    system_idle: bool
    queue_healthy: bool
    database_healthy: bool
    recovery_in_progress: bool
    io_budget_available: bool
    cpu_percent: float
    unconsolidated_salience: float = 0.0
    maintenance_window: bool = False
    event_threshold_met: bool = False
    memory_pressure: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= float(self.cpu_percent) <= 100.0:
            raise ValueError("cpu_percent out of bounds")
        if not 0.0 <= float(self.unconsolidated_salience) <= 1.0:
            raise ValueError("unconsolidated_salience out of bounds")


@dataclass(frozen=True, slots=True)
class ConsolidationScheduleDecision:
    allowed: bool
    trigger: ConsolidationTrigger
    reasons: tuple[str, ...]
    trace: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace", MappingProxyType(dict(self.trace)))


def trigger_for_mode(mode: ConsolidationMode) -> ConsolidationTrigger:
    mapping = {
        ConsolidationMode.MICRO_CONSOLIDATION: ConsolidationTrigger.EVENT_THRESHOLD,
        ConsolidationMode.IDLE_CONSOLIDATION: ConsolidationTrigger.IDLE,
        ConsolidationMode.DAILY_CONSOLIDATION: ConsolidationTrigger.TIME_WINDOW,
        ConsolidationMode.DEEP_CONSOLIDATION: ConsolidationTrigger.TIME_WINDOW,
        ConsolidationMode.MANUAL_CONSOLIDATION: ConsolidationTrigger.MANUAL,
        ConsolidationMode.RECOVERY_CONSOLIDATION: ConsolidationTrigger.RECOVERY,
    }
    return mapping[mode]


def evaluate_schedule(
    mode: ConsolidationMode,
    signals: SchedulerSignals,
    *,
    limits: ConsolidationLimits | None = None,
) -> ConsolidationScheduleDecision:
    cfg = limits or ConsolidationLimits()
    trigger = trigger_for_mode(mode)
    reasons: list[str] = []
    if not signals.database_healthy:
        reasons.append("database_unhealthy")
    if not signals.queue_healthy:
        reasons.append("operational_queue_unhealthy")
    if signals.recovery_in_progress and mode is not ConsolidationMode.RECOVERY_CONSOLIDATION:
        reasons.append("recovery_in_progress")
    if not signals.io_budget_available:
        reasons.append("io_budget_unavailable")
    if float(signals.cpu_percent) > float(cfg.max_cpu_percent):
        reasons.append("cpu_above_limit")
    if trigger is ConsolidationTrigger.IDLE and not signals.system_idle:
        reasons.append("system_not_idle")
    if trigger is ConsolidationTrigger.TIME_WINDOW and not signals.maintenance_window:
        reasons.append("outside_maintenance_window")
    if trigger is ConsolidationTrigger.EVENT_THRESHOLD and not signals.event_threshold_met:
        reasons.append("event_threshold_not_met")
    if trigger is ConsolidationTrigger.MEMORY_PRESSURE and not signals.memory_pressure:
        reasons.append("memory_pressure_not_met")
    if mode is ConsolidationMode.IDLE_CONSOLIDATION and float(signals.unconsolidated_salience) <= 0.0:
        reasons.append("nothing_salient_to_consolidate")
    return ConsolidationScheduleDecision(
        allowed=not reasons,
        trigger=trigger,
        reasons=tuple(reasons),
        trace={
            "mode": mode.value,
            "trigger": trigger.value,
            "system_idle": bool(signals.system_idle),
            "queue_healthy": bool(signals.queue_healthy),
            "database_healthy": bool(signals.database_healthy),
            "recovery_in_progress": bool(signals.recovery_in_progress),
            "io_budget_available": bool(signals.io_budget_available),
            "cpu_percent": float(signals.cpu_percent),
            "max_cpu_percent": float(cfg.max_cpu_percent),
            "unconsolidated_salience": float(signals.unconsolidated_salience),
            "truth_mutated": False,
        },
    )


def validate_candidate(
    *,
    sample_count: int,
    confidence: float,
    conflict: bool,
    proof_count: int,
    limits: ConsolidationLimits | None = None,
) -> tuple[ConsolidationCandidateStatus, tuple[str, ...]]:
    cfg = limits or ConsolidationLimits()
    reasons: list[str] = []
    if int(sample_count) < cfg.min_sample:
        reasons.append("minimum_sample_not_met")
    if int(proof_count) < int(sample_count):
        reasons.append("proof_requirement_not_met")
    if float(confidence) < cfg.min_candidate_confidence:
        reasons.append("confidence_below_threshold")
    if bool(conflict):
        reasons.append("conflict_requires_rejection")
    if reasons:
        return ConsolidationCandidateStatus.REJECTED, tuple(reasons)
    return ConsolidationCandidateStatus.VALIDATED_SHADOW, ()


def consolidation_policy_spec() -> dict[str, Any]:
    limits = ConsolidationLimits()
    return {
        "version": CONSOLIDATION_POLICY_VERSION,
        "capability_class": "OPTIONAL_ASYNC",
        "mode": "SHADOW",
        "truth_mutation_allowed": False,
        "direct_promotion_allowed": False,
        "candidate_state_required": True,
        "proof_requirement": True,
        "conflict_analysis": True,
        "rollback": "DISABLE_COGNITIVE_CONSOLIDATION_AND_IGNORE_DERIVED_STATE",
        "scheduler_triggers": [trigger.value for trigger in ConsolidationTrigger],
        "consolidation_modes": [mode.value for mode in ConsolidationMode],
        "limits": {
            "min_sample": limits.min_sample,
            "max_sources": limits.max_sources,
            "max_candidates": limits.max_candidates,
            "min_candidate_confidence": limits.min_candidate_confidence,
            "max_cpu_percent": limits.max_cpu_percent,
            "max_run_ms": limits.max_run_ms,
            "lease_ttl_seconds": limits.lease_ttl_seconds,
        },
    }
