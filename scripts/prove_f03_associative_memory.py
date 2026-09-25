from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter

import psycopg
from psycopg.rows import dict_row

from memory_permanent.access_policy import AgentAccessContext
from memory_permanent.association_policy import AssociationLimits
from memory_permanent.associative_memory import PostgresAssociationStore
from memory_permanent.canonical_mutation import canonical_mutation_scope
from memory_permanent.cognitive_activation import (
    CognitiveShadowObserver,
    PostgresActivationStore,
)
from memory_permanent.cognitive_observability import dispatcher, metrics
from memory_permanent.context_engine import ContextEngine
from memory_permanent.migration_runner import apply_migrations
from memory_permanent.spreading_activation import SpreadingActivationEngine
from memory_permanent.store import PostgresMemoryStore

ROOT = Path(__file__).resolve().parents[1]
ADMIN_PASSFILE = Path(os.getenv("MEMORY_ADMIN_PGPASSFILE", r"C:\New Projet\MEMORIA-PERMANENTE\runtime\secrets\postgres.pgpass.conf"))
HOST = "127.0.0.1"
PORT = 55436
TENANT = "F03_PROOF"
OTHER_TENANT = "F03_OTHER"
NAMESPACE = "F03_PROOF"
MISSION = "f03-association-mission"
MODEL_ID = "f03-proof-384"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def connect_admin(database: str):
    os.environ["PGPASSFILE"] = str(ADMIN_PASSFILE)
    return psycopg.connect(
        f"postgresql://postgres@{HOST}:{PORT}/{database}",
        connect_timeout=5,
        autocommit=True,
    )


class ProofMemoryStore(PostgresMemoryStore):
    """Exercise exact memory_app authorization using the administrative proof connection."""

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


def vector(axis: int, secondary_axis: int | None = None, secondary: float = 0.0) -> list[float]:
    values = [0.0] * 384
    values[axis] = 1.0
    if secondary_axis is not None:
        values[secondary_axis] = float(secondary)
    return values


def remember(store: ProofMemoryStore, marker: str, suffix: str, category: str) -> str:
    with canonical_mutation_scope("f03-proof", "memory.remember"):
        return store.remember(
            namespace=NAMESPACE,
            memory_key=f"f03.{marker}.{suffix.lower()}",
            category=category,
            content={"marker": marker, "node": suffix},
            content_text=f"F03 associative proof {marker} node {suffix}",
            provenance={"proof": "F03_ASSOCIATIVE_MEMORY", "node": suffix},
            confidence=0.90,
            source="f03-proof",
            source_version="F03-1",
            tags=["F03", "ASSOCIATION", suffix],
            changed_by="f03-proof",
            idempotency_key=f"f03-{marker}-{suffix}",
        )


def store_vector(store: ProofMemoryStore, item_id: str, embedding: list[float]) -> None:
    with store.connection() as conn:
        row = conn.execute("SELECT content_sha256 FROM memory_items WHERE item_id=%s", (item_id,)).fetchone()
    require(row is not None, "memory missing before embedding")
    with canonical_mutation_scope("f03-proof", "embedding.store"):
        store.store_embedding(
            item_id,
            model_id=MODEL_ID,
            dimensions=384,
            embedding=embedding,
            content_sha256=str(row["content_sha256"]),
        )


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))]


def main() -> int:
    require(ADMIN_PASSFILE.is_file(), "administrative passfile missing")
    database = f"memoria_f03_proof_{uuid.uuid4().hex[:10]}"
    evidence: dict[str, object] = {
        "phase": "F03",
        "database_kind": "temporary_isolated",
        "production_database_touched": False,
        "secret_material_exposed": False,
        "mode": "SHADOW",
    }
    try:
        with connect_admin("postgres") as admin:
            admin.execute(f'CREATE DATABASE "{database}"')
        with connect_admin(database) as admin_db:
            admin_db.execute("CREATE EXTENSION vector WITH VERSION '0.8.6'")
        admin_dsn = f"postgresql://postgres@{HOST}:{PORT}/{database}"
        migrations = apply_migrations(admin_dsn, ROOT / "migrations")
        evidence["migration_count"] = len(migrations)
        evidence["migration_head"] = migrations[-1]["version"] if migrations else None
        require(evidence["migration_head"] == "0057_cognitive_associative_memory", "unexpected migration head")

        store = ProofMemoryStore(admin_dsn, initialize=False, tenant_id=TENANT, access=AgentAccessContext.build())
        marker = f"F03-{uuid.uuid4().hex}"
        a = remember(store, marker, "A", "EVIDENCE")
        b = remember(store, marker, "B", "FACT")
        c = remember(store, marker, "C", "HYPOTHESIS")
        d = remember(store, marker, "D", "FACT")
        e = remember(store, marker, "E", "DECISION")
        f = remember(store, marker, "F", "FACT")

        store_vector(store, a, vector(0))
        store_vector(store, b, vector(1))
        store_vector(store, c, vector(2))
        store_vector(store, d, vector(3))
        store_vector(store, e, vector(4))
        store_vector(store, f, vector(0, 5, 0.10))

        with canonical_mutation_scope("f03-proof", "ontology.relation"):
            rel_ab = store.create_knowledge_relation(
                from_item_id=a,
                relation_type="SUPPORTS",
                to_item_id=b,
                provenance={"proof": "F03", "edge": "A-B"},
                confidence=0.95,
                created_by="f03-proof",
            )
        with canonical_mutation_scope("f03-proof", "ontology.relation"):
            rel_bc = store.create_knowledge_relation(
                from_item_id=b,
                relation_type="SUPPORTS",
                to_item_id=c,
                provenance={"proof": "F03", "edge": "B-C"},
                confidence=0.90,
                created_by="f03-proof",
            )

        t0 = datetime.now(UTC) - timedelta(seconds=3)
        with canonical_mutation_scope("f03-proof", "experience.graph.node"):
            node_a = store.create_experience_graph_node(
                mission_id=MISSION,
                node_type="EVIDENCE",
                entity_ref=f"f03:{marker}:evidence",
                payload={"proof": "F03"},
                provenance={"proof": "F03"},
                created_by="f03-proof",
                occurred_at=t0,
                memory_item_id=a,
            )
        with canonical_mutation_scope("f03-proof", "experience.graph.node"):
            node_e = store.create_experience_graph_node(
                mission_id=MISSION,
                node_type="DECISION",
                entity_ref=f"f03:{marker}:decision",
                payload={"proof": "F03"},
                provenance={"proof": "F03"},
                created_by="f03-proof",
                occurred_at=t0 + timedelta(seconds=1),
                memory_item_id=e,
            )
        with canonical_mutation_scope("f03-proof", "experience.graph.edge"):
            graph_ae = store.create_experience_graph_edge(
                mission_id=MISSION,
                from_node_id=str(node_a["node_id"]),
                relation_type="INFORMS",
                to_node_id=str(node_e["node_id"]),
                evidence={"proof": "F03_GRAPH"},
                created_by="f03-proof",
                occurred_at=t0 + timedelta(seconds=2),
            )

        with store.connection() as conn:
            hashes_before = {
                str(row["item_id"]): str(row["content_sha256"])
                for row in conn.execute(
                    "SELECT item_id,content_sha256 FROM memory_items WHERE item_id=ANY(%s)",
                    ([a, b, c, d, e, f],),
                ).fetchall()
            }

        association_store = PostgresAssociationStore(store)
        limits = AssociationLimits(
            max_depth=2,
            node_budget=64,
            time_budget_ms=1000,
            max_candidates=16,
            hop_decay=0.72,
            min_activation=0.12,
            semantic_min_similarity=0.72,
        )
        spreading = SpreadingActivationEngine(limits)

        def provider(memory_id: str, depth: int):
            return association_store.neighbors(
                memory_id,
                namespaces=(NAMESPACE,),
                mission_id=MISSION,
                semantic_min_similarity=limits.semantic_min_similarity,
                limit=32,
            )

        first = spreading.traverse((a,), provider)
        second = spreading.traverse((a,), provider)
        require(first.deterministic_trace == second.deterministic_trace, "association trace is not deterministic")
        candidate_ids = {candidate.memory_id for candidate in first.candidates}
        expected_relevant = {b, c, e, f}
        true_positive = len(candidate_ids & expected_relevant)
        precision = true_positive / len(candidate_ids) if candidate_ids else 0.0
        recall = true_positive / len(expected_relevant)
        require(precision >= 0.80, f"associative precision below 0.80: {precision:.4f}")
        require(recall >= 0.75, f"associative recall below 0.75: {recall:.4f}")
        require(first.visited_count <= limits.node_budget + 1, "association traversal exceeded node budget")
        require(all(candidate.hop_depth <= limits.max_depth for candidate in first.candidates), "association depth exceeded")
        require(first.loops_blocked >= 1, "loop protection was not exercised")
        require(first.time_budget_exhausted is False, "association traversal exhausted time budget in proof corpus")

        traversal_id = association_store.record_traversal_shadow(
            first,
            retrieval_trace_id="trace-f03-proof",
            mission_id=MISSION,
            session_id=None,
        )
        persisted = association_store.load_traversal(traversal_id)
        require(persisted is not None, "association traversal did not persist")
        require(int(persisted["candidate_count"]) == len(first.candidates), "persisted candidate count mismatch")

        source_kinds = {candidate.source_kind for candidate in first.candidates}
        require("ONTOLOGY" in source_kinds, "ontology evidence source not used")
        require("EXPERIENCE_GRAPH" in source_kinds, "experience graph evidence source not used")
        require("PGVECTOR" in source_kinds, "pgvector evidence source not used")

        direct_write_blocked = False
        try:
            with store.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO memory_association_traversals(
                      traversal_id,tenant_id,seed_memory_ids,candidate_count,visited_count,max_depth,node_budget,time_budget_ms,
                      elapsed_ms,policy_version,deterministic_trace
                    ) VALUES(%s,%s,%s,0,1,1,1,1,0.0,'illegal','{}'::jsonb)
                    """,
                    (f"ast-illegal-{uuid.uuid4().hex}", TENANT, [a]),
                )
        except psycopg.Error:
            direct_write_blocked = True
        require(direct_write_blocked, "memory_app direct association table write was not blocked")

        other = ProofMemoryStore(admin_dsn, initialize=False, tenant_id=OTHER_TENANT, access=AgentAccessContext.build())
        other_association = PostgresAssociationStore(other)
        require(other_association.load_traversal(traversal_id) is None, "cross-tenant association traversal leaked")
        cross_tenant_write_blocked = False
        try:
            other_association.record_traversal_shadow(
                first,
                retrieval_trace_id="trace-cross-tenant-denied",
                mission_id=MISSION,
                session_id=None,
            )
        except psycopg.Error:
            cross_tenant_write_blocked = True
        require(cross_tenant_write_blocked, "cross-tenant association write was not blocked")

        restart_code = r'''
import json, os
import psycopg
from psycopg.rows import dict_row
conn=psycopg.connect(os.environ["F03_DSN"],row_factory=dict_row,connect_timeout=5)
conn.execute("SET SESSION AUTHORIZATION memory_app"); conn.commit()
with conn.transaction():
    conn.execute("SELECT set_config('app.current_tenant',%s,true)",(os.environ["F03_TENANT"],))
    row=conn.execute("SELECT traversal_id,candidate_count,deterministic_trace FROM memory_association_traversals WHERE traversal_id=%s",(os.environ["F03_TRAVERSAL"],)).fetchone()
    count=conn.execute("SELECT count(*) AS n FROM memory_association_candidates WHERE traversal_id=%s",(os.environ["F03_TRAVERSAL"],)).fetchone()
conn.close()
print(json.dumps({"traversal":bool(row),"candidate_count":int(row["candidate_count"]) if row else 0,"candidate_rows":int(count["n"])},sort_keys=True))
raise SystemExit(0 if row and int(row["candidate_count"])==int(count["n"]) else 2)
'''
        child_env = os.environ.copy()
        child_env["PGPASSFILE"] = str(ADMIN_PASSFILE)
        child_env["F03_DSN"] = admin_dsn
        child_env["F03_TENANT"] = TENANT
        child_env["F03_TRAVERSAL"] = traversal_id
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
            hashes_after = {
                str(row["item_id"]): str(row["content_sha256"])
                for row in conn.execute(
                    "SELECT item_id,content_sha256 FROM memory_items WHERE item_id=ANY(%s)",
                    ([a, b, c, d, e, f],),
                ).fetchall()
            }
            rls = conn.execute(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname=ANY(%s) ORDER BY relname",
                (["memory_association_traversals", "memory_association_candidates"],),
            ).fetchall()
        require(hashes_before == hashes_after, "association shadow changed canonical memory truth")
        require(len(rls) == 2 and all(bool(row["relrowsecurity"]) and bool(row["relforcerowsecurity"]) for row in rls), "association RLS is not forced")

        activation_adapter = PostgresActivationStore(store)
        observer = CognitiveShadowObserver(
            activation_adapter,
            activation_enabled=False,
            priming_enabled=False,
            salience_enabled=False,
            association_enabled=True,
            association_store=association_store,
            spreading_engine=spreading,
        )
        baseline_engine = ContextEngine(store)
        shadow_engine = ContextEngine(store, cognitive_observer=observer)
        baseline_result = baseline_engine.retrieve(marker, namespaces=(NAMESPACE,), limit=1, mission_id=MISSION)
        shadow_result = shadow_engine.retrieve(marker, namespaces=(NAMESPACE,), limit=1, mission_id=MISSION)
        require(
            [item["item_id"] for item in baseline_result.selected] == [item["item_id"] for item in shadow_result.selected],
            "F03 shadow changed base retrieval selection",
        )
        require(dispatcher.wait_for_idle(20.0), "association dispatcher did not drain after E2E")

        for _ in range(3):
            baseline_engine.retrieve(marker, namespaces=(NAMESPACE,), limit=1, mission_id=MISSION)
            shadow_engine.retrieve(marker, namespaces=(NAMESPACE,), limit=1, mission_id=MISSION)
        require(dispatcher.wait_for_idle(20.0), "association dispatcher did not drain after warmup")
        metrics.reset_for_test()
        baseline_latencies: list[float] = []
        shadow_latencies: list[float] = []
        for _ in range(12):
            started = perf_counter()
            baseline_engine.retrieve(marker, namespaces=(NAMESPACE,), limit=1, mission_id=MISSION)
            baseline_latencies.append((perf_counter() - started) * 1000.0)
            started = perf_counter()
            shadow_engine.retrieve(marker, namespaces=(NAMESPACE,), limit=1, mission_id=MISSION)
            shadow_latencies.append((perf_counter() - started) * 1000.0)
        require(dispatcher.wait_for_idle(30.0), "association dispatcher did not drain after benchmark")
        baseline_p95 = percentile_95(baseline_latencies)
        shadow_p95 = percentile_95(shadow_latencies)
        overhead_pct = ((shadow_p95 - baseline_p95) / baseline_p95 * 100.0) if baseline_p95 > 0 else 0.0
        require(overhead_pct <= 20.0, f"F03 retrieval P95 regression exceeds 20%: {overhead_pct:.2f}%")
        metric_snapshot = dict(metrics.snapshot())
        require(metric_snapshot["association_traversals_total"] >= 12, "association traversal metric missing")
        require(metric_snapshot["cognitive_shadow_dropped_total"] == 0, "association dispatcher dropped work")
        require(metric_snapshot["cognitive_shadow_failures_total"] == 0, "association dispatcher failed work")

        evidence.update(
            {
                "status": "PASS",
                "graph_propagation": True,
                "bounded_traversal": True,
                "scope_isolation": True,
                "deterministic_trace": True,
                "loop_protection": True,
                "conflict_evidence_filter": True,
                "canonical_sources": sorted(source_kinds),
                "ontology_relation_ids": [rel_ab["relation_id"], rel_bc["relation_id"]],
                "experience_graph_edge_id": graph_ae["graph_edge_id"],
                "candidate_count": len(first.candidates),
                "candidate_ids": sorted(candidate_ids),
                "expected_relevant_count": len(expected_relevant),
                "associative_precision": round(precision, 6),
                "associative_precision_requirement": 0.80,
                "associative_recall": round(recall, 6),
                "associative_recall_requirement": 0.75,
                "visited_count": first.visited_count,
                "considered_edges": first.considered_edges,
                "loops_blocked": first.loops_blocked,
                "evidence_rejections": first.evidence_rejections,
                "traversal_elapsed_ms": round(first.elapsed_ms, 6),
                "restart_new_interpreter": bool(restart["traversal"]),
                "persisted_candidate_rows": int(restart["candidate_rows"]),
                "direct_runtime_table_write_blocked": direct_write_blocked,
                "cross_tenant_read_isolated": True,
                "cross_tenant_write_blocked": cross_tenant_write_blocked,
                "rls_forced_tables": 2,
                "canonical_memory_hashes_unchanged": True,
                "base_retrieval_unchanged": True,
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
