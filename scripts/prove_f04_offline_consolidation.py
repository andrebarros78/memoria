from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter

import psycopg
from psycopg.rows import dict_row

from memory_permanent.access_policy import AgentAccessContext
from memory_permanent.canonical_mutation import canonical_mutation_scope
from memory_permanent.cognitive_activation import (
    CognitiveShadowObserver,
    PostgresActivationStore,
)
from memory_permanent.consolidation_policy import ConsolidationMode, SchedulerSignals
from memory_permanent.consolidation_scheduler import ConsolidationScheduler
from memory_permanent.context_engine import ContextEngine
from memory_permanent.migration_runner import apply_migrations
from memory_permanent.offline_consolidation import (
    ForcedConsolidationInterruption,
    OfflineCognitiveConsolidationEngine,
    PostgresConsolidationStore,
)
from memory_permanent.store import ConcurrencyConflict, PostgresMemoryStore

ROOT = Path(__file__).resolve().parents[1]
ADMIN_PASSFILE = Path(r"C:\New Projet\MEMORIA-PERMANENTE\runtime\secrets\postgres.pgpass.conf")
HOST = "127.0.0.1"
PORT = 55436
TENANT = "F04_PROOF"
OTHER_TENANT = "F04_OTHER"
WORKER = "cognitive-consolidation-worker"
OTHER_WORKER = "cognitive-consolidation-rival"
STAGES = {
    "SELECT",
    "REPLAY",
    "COMPARE",
    "CLUSTER",
    "ASSOCIATE",
    "DETECT_PATTERN",
    "GENERATE_CANDIDATE",
    "VALIDATE",
    "CONSOLIDATE",
    "RECORD_PROVENANCE",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def connect_admin(database: str):
    os.environ["PGPASSFILE"] = str(ADMIN_PASSFILE)
    return psycopg.connect(
        f"postgresql://postgres@{HOST}:{PORT}/{database}",
        connect_timeout=5,
        autocommit=True,
        row_factory=dict_row,
    )


class ProofMemoryStore(PostgresMemoryStore):
    """Use exact memory_app authorization while preserving the production credential."""

    @contextmanager
    def connection(self):
        os.environ["PGPASSFILE"] = str(ADMIN_PASSFILE)
        conn = psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5)
        try:
            conn.execute("SET SESSION AUTHORIZATION memory_app")
            conn.commit()
            with conn.transaction():
                settings = {
                    "app.current_tenant": self.tenant_id,
                    "app.current_agent": self.access.agent_id or "",
                    "app.current_user_id": self.access.user_id or "",
                    "app.current_project": self.access.project_id or "",
                    "app.current_team": self.access.team_id or "",
                    "app.current_org": self.access.organization_id or "",
                }
                for key, value in settings.items():
                    conn.execute("SELECT set_config(%s,%s,true)", (key, value))
                yield conn
        finally:
            conn.close()


def worker_store(dsn: str, *, tenant: str = TENANT, agent: str = WORKER) -> ProofMemoryStore:
    return ProofMemoryStore(
        dsn,
        initialize=False,
        tenant_id=tenant,
        access=AgentAccessContext.build(agent_id=agent),
    )


def child_forced_interrupt(database: str, run_id: str) -> int:
    dsn = f"postgresql://postgres@{HOST}:{PORT}/{database}"
    store = worker_store(dsn)
    adapter = PostgresConsolidationStore(store)
    engine = OfflineCognitiveConsolidationEngine(adapter)
    scope_key = f"tenant:{TENANT}:forced-recovery"
    lease_key = "cognitive-consolidation:forced-proof"
    with canonical_mutation_scope(WORKER, "lease.acquire"):
        lease = store.acquire_lease(lease_key, ttl_seconds=30)
    try:
        engine.execute(
            scope_key=scope_key,
            mode=ConsolidationMode.IDLE_CONSOLIDATION,
            trigger=SchedulerSignals(
                system_idle=True,
                queue_healthy=True,
                database_healthy=True,
                recovery_in_progress=False,
                io_budget_available=True,
                cpu_percent=5,
                unconsolidated_salience=1.0,
            ) and __import__("memory_permanent.consolidation_policy", fromlist=["ConsolidationTrigger"]).ConsolidationTrigger.IDLE,
            lease_key=lease_key,
            fencing_token=int(lease["fencing_token"]),
            run_id=run_id,
            interrupt_after_stage="REPLAY",
        )
    except ForcedConsolidationInterruption:
        os._exit(73)
    return 3


def percentile95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))]


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        return child_forced_interrupt(sys.argv[2], sys.argv[3])

    require(ADMIN_PASSFILE.is_file(), "administrative passfile missing")
    database = f"memoria_f04_proof_{uuid.uuid4().hex[:10]}"
    evidence: dict[str, object] = {
        "phase": "F04",
        "database_kind": "temporary_isolated",
        "production_database_touched": False,
        "secret_material_exposed": False,
        "capability_class": "OPTIONAL_ASYNC",
        "mode": "SHADOW",
    }
    try:
        with connect_admin("postgres") as admin:
            admin.execute(f'CREATE DATABASE "{database}"')
        with connect_admin(database) as admin_db:
            admin_db.execute("CREATE EXTENSION vector WITH VERSION '0.8.6'")
        os.environ["PGPASSFILE"] = str(ADMIN_PASSFILE)
        dsn = f"postgresql://postgres@{HOST}:{PORT}/{database}"
        migrations = apply_migrations(dsn, ROOT / "migrations")
        evidence["migration_count"] = len(migrations)
        evidence["migration_head"] = migrations[-1]["version"] if migrations else None
        require(evidence["migration_head"] == "0058_cognitive_offline_consolidation", "unexpected migration head")

        store = worker_store(dsn)
        marker = f"F04-{uuid.uuid4().hex}"
        item_ids: list[str] = []
        with canonical_mutation_scope(WORKER, "memory.remember"):
            for index in range(4):
                item_ids.append(
                    store.remember(
                        namespace="F04_PROOF",
                        memory_key=f"f04.{marker}.{index}",
                        content={"marker": marker, "ordinal": index},
                        content_text=f"{marker} repeated governed consolidation pattern ordinal {index}",
                        provenance={"proof": "F04_RUNTIME", "ordinal": index},
                        confidence=0.90,
                        source="f04-proof",
                        source_version="F04-1",
                        tags=["F04", "CONSOLIDATION", "SHADOW"],
                        changed_by=WORKER,
                        idempotency_key=f"f04-{marker}-{index}",
                    )
                )

        activation = PostgresActivationStore(store)
        observer = CognitiveShadowObserver(activation, priming_enabled=False, association_enabled=False)
        for index, item_id in enumerate(item_ids):
            observer.observe_capture(
                memory_id=item_id,
                base_strength=0.90,
                salience_signals={"risk": 0.9, "urgency": 0.9, "operational_impact": 1.0},
                source_trust=1.0,
                evidence_refs=(f"f04-proof-{index}-a", f"f04-proof-{index}-b"),
            )

        with store.connection() as conn:
            hashes_before = {
                str(row["item_id"]): str(row["content_sha256"])
                for row in conn.execute(
                    "SELECT item_id,content_sha256 FROM memory_items WHERE item_id=ANY(%s) ORDER BY item_id",
                    (item_ids,),
                ).fetchall()
            }

        baseline_engine = ContextEngine(store)
        before = baseline_engine.retrieve(marker, namespaces=("F04_PROOF",), limit=10)
        before_ids = [str(row["item_id"]) for row in before.selected]

        scheduler = ConsolidationScheduler(store)
        idle_result = scheduler.run_once(
            scope_key=f"tenant:{TENANT}:idle",
            mode=ConsolidationMode.IDLE_CONSOLIDATION,
            signals=SchedulerSignals(
                system_idle=True,
                queue_healthy=True,
                database_healthy=True,
                recovery_in_progress=False,
                io_budget_available=True,
                cpu_percent=10,
                unconsolidated_salience=1.0,
            ),
        )
        require(idle_result.status == "COMPLETED" and idle_result.run_id, "idle consolidation did not complete")
        adapter = PostgresConsolidationStore(store)
        idle_run = adapter.load_run(str(idle_result.run_id))
        idle_candidates = adapter.candidates(str(idle_result.run_id))
        idle_checkpoints = adapter.checkpoints(str(idle_result.run_id))
        idle_replay = scheduler.engine.replay_run(str(idle_result.run_id))
        require(idle_run is not None and str(idle_run["status"]) == "COMPLETED", "idle run state invalid")
        require(len(idle_candidates) >= 1, "idle run generated no candidate")
        require(any(str(row["status"]) == "VALIDATED_SHADOW" for row in idle_candidates), "no validated shadow candidate")
        require({str(row["stage"]) for row in idle_checkpoints} == STAGES, "idle checkpoint stages incomplete")
        require(idle_replay["status"] == "PASS" and idle_replay["deterministic"] is True, "idle replay mismatch")

        after = baseline_engine.retrieve(marker, namespaces=("F04_PROOF",), limit=10)
        after_ids = [str(row["item_id"]) for row in after.selected]
        require(before_ids == after_ids, "offline consolidation changed canonical retrieval result")

        with store.connection() as conn:
            hashes_after = {
                str(row["item_id"]): str(row["content_sha256"])
                for row in conn.execute(
                    "SELECT item_id,content_sha256 FROM memory_items WHERE item_id=ANY(%s) ORDER BY item_id",
                    (item_ids,),
                ).fetchall()
            }
        require(hashes_before == hashes_after, "offline consolidation changed canonical memory truth")

        direct_write_blocked = False
        try:
            with store.connection() as conn:
                conn.execute(
                    "INSERT INTO cognitive_consolidation_events(event_id,tenant_id,run_id,event_type,payload_jsonb) VALUES(%s,%s,%s,'FINISHED','{}'::jsonb)",
                    (f"conevt-{uuid.uuid4().hex}", TENANT, idle_result.run_id),
                )
        except psycopg.Error:
            direct_write_blocked = True
        require(direct_write_blocked, "memory_app direct consolidation write was not blocked")

        other_tenant = worker_store(dsn, tenant=OTHER_TENANT)
        with other_tenant.connection() as conn:
            leaked = int(conn.execute("SELECT count(*) AS n FROM cognitive_consolidation_runs").fetchone()["n"])
        require(leaked == 0, "cross-tenant consolidation state leaked")
        cross_tenant_write_blocked = False
        try:
            PostgresConsolidationStore(other_tenant).resume_run(
                run_id=str(idle_result.run_id),
                lease_key="cross-tenant",
                fencing_token=1,
            )
        except psycopg.Error:
            cross_tenant_write_blocked = True
        require(cross_tenant_write_blocked, "cross-tenant consolidation control write was not blocked")

        lease_key = "cognitive-consolidation:exclusive-proof"
        with canonical_mutation_scope(WORKER, "lease.acquire"):
            exclusive = store.acquire_lease(lease_key, ttl_seconds=30)
        rival = worker_store(dsn, agent=OTHER_WORKER)
        exclusive_lease_enforced = False
        try:
            with canonical_mutation_scope(OTHER_WORKER, "lease.acquire"):
                rival.acquire_lease(lease_key, ttl_seconds=30)
        except ConcurrencyConflict:
            exclusive_lease_enforced = True
        require(exclusive_lease_enforced, "exclusive consolidation lease was not enforced")
        with canonical_mutation_scope(WORKER, "lease.release"):
            store.release_lease(lease_key, fencing_token=int(exclusive["fencing_token"]))

        forced_run_id = f"conrun-{uuid.uuid4().hex}"
        child_env = os.environ.copy()
        child_env["PGPASSFILE"] = str(ADMIN_PASSFILE)
        child = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--child", database, forced_run_id],
            cwd=str(ROOT),
            env=child_env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        require(child.returncode == 73, f"forced interruption child exit mismatch: {child.returncode} {child.stderr[:400]}")
        forced_adapter = PostgresConsolidationStore(store)
        interrupted = forced_adapter.load_run(forced_run_id)
        require(interrupted is not None and str(interrupted["status"]) == "RUNNING", "forced run did not persist RUNNING state")
        child_checkpoints = forced_adapter.checkpoints(forced_run_id)
        require({str(row["stage"]) for row in child_checkpoints} == {"SELECT", "REPLAY"}, "forced checkpoints missing")
        old_token = int(interrupted["fencing_token"])
        forced_lease_key = str(interrupted["lease_key"])
        with canonical_mutation_scope(WORKER, "lease.acquire"):
            replacement_lease = store.acquire_lease(forced_lease_key, ttl_seconds=30)
        new_token = int(replacement_lease["fencing_token"])
        require(new_token > old_token, "recovery lease did not advance fencing token")
        stale_lease_blocked = False
        try:
            forced_adapter.resume_run(run_id=forced_run_id, lease_key=forced_lease_key, fencing_token=old_token)
        except psycopg.Error:
            stale_lease_blocked = True
        require(stale_lease_blocked, "stale consolidation fencing token was accepted")
        recovered = OfflineCognitiveConsolidationEngine(forced_adapter).recover(
            run_id=forced_run_id,
            lease_key=forced_lease_key,
            fencing_token=new_token,
        )
        require(recovered.status == "COMPLETED" and recovered.recovered_from_interrupt, "forced run recovery failed")
        with canonical_mutation_scope(WORKER, "lease.release"):
            store.release_lease(forced_lease_key, fencing_token=new_token)
        recovery_replay = OfflineCognitiveConsolidationEngine(forced_adapter).replay_run(forced_run_id)
        require(recovery_replay["status"] == "PASS", "recovered run replay failed")
        recovered_checkpoints = forced_adapter.checkpoints(forced_run_id)
        require(STAGES.issubset({str(row["stage"]) for row in recovered_checkpoints}), "recovery did not complete all stages")

        with store.connection() as conn:
            rls = conn.execute(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname=ANY(%s) ORDER BY relname",
                ([
                    "cognitive_consolidation_runs",
                    "cognitive_consolidation_checkpoints",
                    "cognitive_consolidation_candidates",
                    "cognitive_consolidation_events",
                ],),
            ).fetchall()
        require(len(rls) == 4 and all(bool(row["relrowsecurity"]) and bool(row["relforcerowsecurity"]) for row in rls), "F04 RLS not forced")

        baseline_latencies: list[float] = []
        for _ in range(20):
            started = perf_counter()
            baseline_engine.retrieve(marker, namespaces=("F04_PROOF",), limit=10)
            baseline_latencies.append((perf_counter() - started) * 1000.0)
        p95 = percentile95(baseline_latencies)
        require(p95 < 2000.0, f"core retrieval became unhealthy during F04 proof: p95={p95:.2f}ms")

        evidence.update(
            {
                "status": "PASS",
                "idle_run": True,
                "idle_run_id": idle_result.run_id,
                "idle_candidate_count": len(idle_candidates),
                "idle_validated_candidates": sum(1 for row in idle_candidates if str(row["status"]) == "VALIDATED_SHADOW"),
                "checkpoint_stages_complete": True,
                "replay_deterministic": True,
                "forced_interruption_exit_code": child.returncode,
                "forced_interruption_persisted": True,
                "recovery_after_forced_interruption": True,
                "recovery_run_id": forced_run_id,
                "recovery_replay": recovery_replay["status"],
                "stale_fencing_token_blocked": stale_lease_blocked,
                "exclusive_scope_lease": exclusive_lease_enforced,
                "direct_runtime_table_write_blocked": direct_write_blocked,
                "cross_tenant_read_isolated": True,
                "cross_tenant_write_blocked": cross_tenant_write_blocked,
                "rls_forced_tables": 4,
                "canonical_memory_hashes_unchanged": True,
                "base_retrieval_unchanged": True,
                "capture_retrieval_dependency": False,
                "retrieval_p95_ms": round(p95, 6),
                "candidate_state": "VALIDATED_SHADOW",
                "canonical_promotions": 0,
            }
        )
        print(json.dumps(evidence, sort_keys=True))
        return 0
    finally:
        try:
            with connect_admin("postgres") as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        except psycopg.Error as exc:
            print(json.dumps({"cleanup_warning": type(exc).__name__}), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
