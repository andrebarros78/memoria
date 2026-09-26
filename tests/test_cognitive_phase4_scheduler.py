from __future__ import annotations

from types import SimpleNamespace

from memory_permanent.consolidation_policy import ConsolidationMode, SchedulerSignals
from memory_permanent.consolidation_scheduler import (
    ConsolidationScheduler,
    consolidation_scheduler_spec,
)


class _Access:
    agent_id = "cognitive-consolidation-worker"


class _MemoryStore:
    access = _Access()

    def __init__(self) -> None:
        self.acquired: list[str] = []
        self.released: list[tuple[str, int]] = []

    def acquire_lease(self, lease_key: str, *, ttl_seconds: int):
        self.acquired.append(lease_key)
        return {"fencing_token": 7, "lease_key": lease_key, "ttl_seconds": ttl_seconds}

    def release_lease(self, lease_key: str, *, fencing_token: int):
        self.released.append((lease_key, fencing_token))
        return {"lease_key": lease_key, "fencing_token": fencing_token}


class _Engine:
    def execute(self, **kwargs):
        return SimpleNamespace(
            status="COMPLETED",
            run_id="conrun-" + "a" * 32,
            recovered_from_interrupt=False,
        )

    def recover(self, **kwargs):
        return SimpleNamespace(
            status="COMPLETED",
            mode="IDLE_CONSOLIDATION",
            run_id=kwargs["run_id"],
            recovered_from_interrupt=True,
        )


class _Store:
    def load_run(self, run_id: str):
        return {"run_id": run_id, "scope_key": "tenant:project", "trigger_kind": "IDLE"}


def _healthy() -> SchedulerSignals:
    return SchedulerSignals(
        system_idle=True,
        queue_healthy=True,
        database_healthy=True,
        recovery_in_progress=False,
        io_budget_available=True,
        cpu_percent=10,
        unconsolidated_salience=0.8,
    )


def test_phase4_scheduler_is_portable_one_shot_not_host_cron():
    spec = consolidation_scheduler_spec()
    assert spec["host_coupled"] is False
    assert spec["execution_model"] == "PORTABLE_ONE_SHOT_WORKER"
    assert spec["exclusive_scope_lease"] is True
    assert spec["fencing_token_required"] is True
    assert spec["default_enabled"] is False
    assert spec["capture_retrieval_blocking"] is False


def test_phase4_scheduler_skips_without_lease_when_idle_gate_denied():
    memory = _MemoryStore()
    scheduler = ConsolidationScheduler(memory)
    scheduler.engine = _Engine()
    result = scheduler.run_once(
        scope_key="tenant:project",
        mode=ConsolidationMode.IDLE_CONSOLIDATION,
        signals=SchedulerSignals(
            system_idle=False,
            queue_healthy=True,
            database_healthy=True,
            recovery_in_progress=False,
            io_budget_available=True,
            cpu_percent=10,
            unconsolidated_salience=0.8,
        ),
    )
    assert result.status == "SKIPPED"
    assert memory.acquired == []
    assert memory.released == []


def test_phase4_scheduler_uses_exclusive_lease_and_releases_after_success():
    memory = _MemoryStore()
    scheduler = ConsolidationScheduler(memory)
    scheduler.engine = _Engine()
    result = scheduler.run_once(
        scope_key="tenant:project",
        mode=ConsolidationMode.IDLE_CONSOLIDATION,
        signals=_healthy(),
    )
    assert result.status == "COMPLETED"
    assert len(memory.acquired) == 1
    assert memory.released == [(memory.acquired[0], 7)]


def test_phase4_scheduler_recovery_reacquires_fenced_lease():
    memory = _MemoryStore()
    scheduler = ConsolidationScheduler(memory)
    scheduler.store = _Store()
    scheduler.engine = _Engine()
    run_id = "conrun-" + "b" * 32
    result = scheduler.recover_run(run_id)
    assert result.status == "COMPLETED"
    assert result.recovered is True
    assert len(memory.acquired) == 1
    assert memory.released == [(memory.acquired[0], 7)]
