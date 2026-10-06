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

from memory_permanent.canonical_mutation import canonical_mutation_scope
from memory_permanent.cognitive_activation import (
    CognitiveActivationEngine,
    CognitiveShadowObserver,
    PostgresActivationStore,
)
from memory_permanent.cognitive_contracts import CognitiveScope
from memory_permanent.cognitive_observability import dispatcher, metrics
from memory_permanent.context_engine import ContextEngine
from memory_permanent.migration_runner import apply_migrations
from memory_permanent.store import PostgresMemoryStore

ROOT = Path(__file__).resolve().parents[1]
ADMIN_PASSFILE = Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0\runtime\secrets\postgres.pgpass.conf")
HOST = "127.0.0.1"
PORT = 55436
TENANT = "F02_PROOF"
OTHER_TENANT = "F02_OTHER"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def connect_admin(database: str):
    os.environ["PGPASSFILE"] = str(ADMIN_PASSFILE)
    return psycopg.connect(f"postgresql://postgres@{HOST}:{PORT}/{database}", connect_timeout=5, autocommit=True)


class ProofMemoryStore(PostgresMemoryStore):
    """Exercise exact memory_app authorization without changing its production credential."""

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


def main() -> int:
    require(ADMIN_PASSFILE.is_file(), "administrative passfile missing")
    database = f"memoria_f02_proof_{uuid.uuid4().hex[:10]}"
    evidence: dict[str, object] = {
        "phase": "F02",
        "database_kind": "temporary_isolated",
        "production_database_touched": False,
        "secret_material_exposed": False,
    }
    try:
        with connect_admin("postgres") as admin:
            admin.execute(f'CREATE DATABASE "{database}"')
        with connect_admin(database) as admin_db:
            admin_db.execute("CREATE EXTENSION vector WITH VERSION '0.8.6'")
        os.environ["PGPASSFILE"] = str(ADMIN_PASSFILE)
        admin_dsn = f"postgresql://postgres@{HOST}:{PORT}/{database}"
        migrations = apply_migrations(admin_dsn, ROOT / "migrations")
        evidence["migration_count"] = len(migrations)
        evidence["migration_head"] = migrations[-1]["version"] if migrations else None
        require(evidence["migration_head"] == "0056_cognitive_salience", "unexpected migration head")

        dsn = admin_dsn
        store = ProofMemoryStore(dsn, initialize=False, tenant_id=TENANT)
        marker = f"F02-{uuid.uuid4().hex}"
        with canonical_mutation_scope("f02-proof", "memory.remember"):
            item_id = store.remember(
                namespace="F02_PROOF",
                memory_key=f"f02.{marker}",
                content={"marker": marker},
                content_text=f"F02 cognitive activation persistence proof {marker}",
                provenance={
                    "proof": "F02_RUNTIME",
                    "salience_signals": {"risk": 0.8, "urgency": 0.7, "operational_impact": 0.9},
                    "evidence_refs": ["proof-e1", "proof-e2"],
                },
                confidence=0.82,
                source="f02-proof",
                source_version="F02-1",
                tags=["F02", "COGNITIVE", "SHADOW"],
                changed_by="f02-proof",
                idempotency_key=f"f02-{marker}",
            )

        adapter = PostgresActivationStore(store)
        observer = CognitiveShadowObserver(adapter)
        scope = CognitiveScope(TENANT, "proof-owner")
        observer.observe_capture(
            memory_id=item_id,
            base_strength=0.82,
            salience_signals={"risk": 0.8, "urgency": 0.7, "operational_impact": 0.9},
            source_trust=1.0,
            evidence_refs=("proof-e1", "proof-e2"),
        )
        prime = observer.prime(
            target_memory_id=item_id,
            source_scope=scope,
            target_scope=scope,
            requested_boost=0.12,
            source_trust=1.0,
            budget_remaining=0.2,
            evidence_refs=("proof-e1", "proof-e2"),
            source_memory_id=item_id,
            ttl_seconds=3600,
        )
        require(prime.allowed and prime.boost > 0.0, "priming was not recorded")

        engine = CognitiveActivationEngine()
        persisted = adapter.load_activation_state(item_id)
        require(persisted is not None, "activation state missing after capture")
        second = engine.compute(
            memory_id=item_id,
            base_strength=float(persisted["base_strength"]),
            last_activated_at=persisted["activation_updated_at"],
            access_count=int(persisted["access_count"]) + 1,
            priming_weight=adapter.load_priming_weight(item_id),
            trace_id="f02-runtime-proof",
        )
        adapter.record_activation_shadow(second, trace_id="f02-runtime-proof")

        with store.connection() as conn:
            salience_count = int(conn.execute("SELECT count(*) AS n FROM memory_salience WHERE memory_id=%s", (item_id,)).fetchone()["n"])
            activation_events = int(conn.execute("SELECT count(*) AS n FROM memory_activation_events WHERE memory_id=%s", (item_id,)).fetchone()["n"])
            item_hash_before = str(conn.execute("SELECT content_sha256 FROM memory_items WHERE item_id=%s", (item_id,)).fetchone()["content_sha256"])
        require(salience_count >= 1, "salience persistence missing")
        require(activation_events >= 2, "activation event history missing")

        direct_write_blocked = False
        try:
            with store.connection() as conn:
                conn.execute(
                    "INSERT INTO memory_activation_events(event_id,tenant_id,memory_id,event_type,activation_level,components_jsonb,policy_version) VALUES(%s,%s,%s,'ACTIVATION',0.5,'{}'::jsonb,'illegal')",
                    (f"actevt-{uuid.uuid4().hex}", TENANT, item_id),
                )
        except psycopg.Error:
            direct_write_blocked = True
        require(direct_write_blocked, "memory_app direct cognitive table write was not blocked")

        other = ProofMemoryStore(dsn, initialize=False, tenant_id=OTHER_TENANT)
        other_adapter = PostgresActivationStore(other)
        require(other_adapter.load_activation_state(item_id) is None, "cross-tenant activation state leaked")
        cross_tenant_write_blocked = False
        try:
            other_adapter.record_activation_shadow(second, trace_id="cross-tenant-denied")
        except psycopg.Error:
            cross_tenant_write_blocked = True
        require(cross_tenant_write_blocked, "cross-tenant cognitive write was not blocked")

        restart_code = r'''
import json, os, sys
import psycopg
from psycopg.rows import dict_row
conn=psycopg.connect(os.environ["F02_DSN"],row_factory=dict_row,connect_timeout=5)
conn.execute("SET SESSION AUTHORIZATION memory_app"); conn.commit()
with conn.transaction():
    conn.execute("SELECT set_config('app.current_tenant',%s,true)",(os.environ["F02_TENANT"],))
    item=os.environ["F02_ITEM"]
    state=conn.execute("SELECT activation_level FROM memory_activation_state WHERE memory_id=%s",(item,)).fetchone()
    prime=conn.execute("SELECT COALESCE(sum(weight),0.0) AS weight FROM memory_priming_edges WHERE target_memory_id=%s AND (valid_until IS NULL OR valid_until>now())",(item,)).fetchone()
    sal=conn.execute("SELECT count(*) AS n FROM memory_salience WHERE memory_id=%s",(item,)).fetchone()
conn.close()
print(json.dumps({"state": bool(state), "activation_level": float(state["activation_level"]) if state else None, "priming_weight": float(prime["weight"]), "salience_rows": int(sal["n"])},sort_keys=True))
raise SystemExit(0 if state and int(sal["n"])>0 else 2)
'''
        child_env = os.environ.copy()
        child_env["PGPASSFILE"] = str(ADMIN_PASSFILE)
        child_env["F02_DSN"] = dsn
        child_env["F02_TENANT"] = TENANT
        child_env["F02_ITEM"] = item_id
        child = subprocess.run(
            [sys.executable, "-c", restart_code],
            cwd=str(ROOT),
            env=child_env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        require(child.returncode == 0, f"restart child failed: {child.stderr[:500]}")
        restart = json.loads(child.stdout.strip())

        with store.connection() as conn:
            item_hash_after = str(conn.execute("SELECT content_sha256 FROM memory_items WHERE item_id=%s", (item_id,)).fetchone()["content_sha256"])
            rls = conn.execute(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname=ANY(%s) ORDER BY relname",
                (["memory_activation_state", "memory_activation_events", "memory_priming_edges", "memory_interference_events", "memory_salience"],),
            ).fetchall()
        require(item_hash_before == item_hash_after, "cognitive shadow changed canonical memory truth")
        require(len(rls) == 5 and all(bool(row["relrowsecurity"]) and bool(row["relforcerowsecurity"]) for row in rls), "cognitive RLS is not forced")

        baseline_engine = ContextEngine(store)
        shadow_engine = ContextEngine(store, cognitive_observer=observer)
        for _ in range(5):
            baseline_engine.retrieve(marker, namespaces=("F02_PROOF",), limit=4)
            shadow_engine.retrieve(marker, namespaces=("F02_PROOF",), limit=4)
        require(dispatcher.wait_for_idle(20.0), "cognitive dispatcher did not drain after warmup")
        metrics.reset_for_test()
        baseline_latencies: list[float] = []
        shadow_latencies: list[float] = []
        for _ in range(24):
            started = perf_counter()
            baseline_engine.retrieve(marker, namespaces=("F02_PROOF",), limit=4)
            baseline_latencies.append((perf_counter() - started) * 1000.0)
            started = perf_counter()
            shadow_engine.retrieve(marker, namespaces=("F02_PROOF",), limit=4)
            shadow_latencies.append((perf_counter() - started) * 1000.0)
        require(dispatcher.wait_for_idle(30.0), "cognitive dispatcher did not drain after benchmark")

        def percentile_95(values: list[float]) -> float:
            ordered = sorted(values)
            return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))]

        baseline_p95 = percentile_95(baseline_latencies)
        shadow_p95 = percentile_95(shadow_latencies)
        overhead_pct = ((shadow_p95 - baseline_p95) / baseline_p95 * 100.0) if baseline_p95 > 0 else 0.0
        require(overhead_pct <= 20.0, f"retrieval P95 regression exceeds 20%: {overhead_pct:.2f}%")
        metric_snapshot = dict(metrics.snapshot())
        require(metric_snapshot["cognitive_shadow_dropped_total"] == 0, "shadow dispatcher dropped benchmark work")
        require(metric_snapshot["cognitive_shadow_failures_total"] == 0, "shadow dispatcher failed benchmark work")

        evidence.update(
            {
                "status": "PASS",
                "activation_persisted": True,
                "priming_persisted": restart["priming_weight"] > 0,
                "salience_persisted": restart["salience_rows"] > 0,
                "restart_new_interpreter": True,
                "direct_runtime_table_write_blocked": direct_write_blocked,
                "cross_tenant_read_isolated": True,
                "cross_tenant_write_blocked": cross_tenant_write_blocked,
                "rls_forced_tables": 5,
                "canonical_memory_hash_unchanged": True,
                "activation_events": activation_events,
                "salience_rows": salience_count,
                "priming_boost": prime.boost,
                "retrieval_baseline_p95_ms": round(baseline_p95, 6),
                "retrieval_shadow_p95_ms": round(shadow_p95, 6),
                "retrieval_p95_overhead_percent": round(overhead_pct, 6),
                "retrieval_p95_requirement_percent": 20.0,
                "cognitive_metrics": metric_snapshot,
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
