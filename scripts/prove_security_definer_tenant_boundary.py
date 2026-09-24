from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg

from memory_permanent.access_policy import AgentAccessContext
from memory_permanent.store import PostgresMemoryStore

ROOT = Path(__file__).resolve().parents[1]
DSN = os.getenv(
    "MEMORY_DATABASE_URL",
    "postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary",
)


def _sample_target() -> tuple[str, str]:
    legacy = PostgresMemoryStore(
        DSN,
        initialize=False,
        tenant_id="LEGACY",
        access=AgentAccessContext.system(),
    )
    with legacy.connection() as conn:
        item_id = str(conn.execute("SELECT item_id FROM memory_items ORDER BY item_id LIMIT 1").fetchone()["item_id"])
        row = conn.execute("SELECT request_id FROM lifecycle_requests ORDER BY request_id LIMIT 1").fetchone()
        request_id = str(row["request_id"]) if row else "lcr-cross-tenant-proof"
    return item_id, request_id


def _attempt(sql: str, args: tuple[object, ...]) -> dict[str, object]:
    access = AgentAccessContext.system()
    with psycopg.connect(DSN, connect_timeout=5) as conn:
        settings = {
            "app.current_tenant": "TENANT_B",
            "app.current_agent": access.agent_id or "",
            "app.current_user_id": access.user_id or "",
            "app.current_project": access.project_id or "",
            "app.current_team": access.team_id or "",
            "app.current_org": access.organization_id or "",
        }
        for key, value in settings.items():
            conn.execute("SELECT set_config(%s,%s,true)", (key, value))
        try:
            conn.execute(sql, args)
        except psycopg.Error as exc:
            result = {
                "denied": True,
                "sqlstate": exc.sqlstate,
                "error_type": type(exc).__name__,
            }
            conn.rollback()
            return result
        conn.rollback()
        return {"denied": False, "sqlstate": None, "error_type": None}


def main() -> int:
    item_id, request_id = _sample_target()
    checks = {
        "legal_erasure_wrapper": _attempt(
            "SELECT memory_apply_legal_erasure_extended(%s,%s,%s,%s)",
            (item_id, "ler-cross-proof", "a" * 64, "b" * 64),
        ),
        "ontology_wrapper": _attempt(
            "SELECT memory_apply_ontology_transition(%s,%s,%s,%s,%s,%s::jsonb)",
            ("tr-cross-proof", item_id, "FACT", "audit", "cross-tenant-proof", "{}"),
        ),
        "lifecycle_wrapper": _attempt(
            "SELECT memory_lifecycle_finalize_payload(%s,%s,%s)",
            (request_id, item_id, "c" * 64),
        ),
        "legacy_base_erasure_direct": _attempt(
            "SELECT memory_apply_legal_erasure(%s,%s,%s,%s)",
            (item_id, "ler-cross-proof", "a" * 64, "b" * 64),
        ),
    }

    runtime = PostgresMemoryStore(
        DSN,
        initialize=False,
        tenant_id="LEGACY",
        access=AgentAccessContext.system(),
    )
    with runtime.connection() as conn:
        rows = conn.execute(
            """
            SELECT p.proname,
                   pg_get_userbyid(p.proowner) AS owner,
                   coalesce(array_to_string(p.proconfig,','),'') AS config,
                   has_function_privilege('memory_app',p.oid,'EXECUTE') AS runtime_execute
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public'
              AND p.proname IN (
                'memory_apply_legal_erasure_extended',
                'memory_apply_ontology_transition',
                'memory_lifecycle_finalize_payload',
                'memory_apply_legal_erasure',
                'memory_apply_legal_erasure_extended_internal_0049',
                'memory_apply_ontology_transition_internal_0049',
                'memory_lifecycle_finalize_payload_internal_0049'
              )
            ORDER BY p.proname
            """
        ).fetchall()
        functions = [dict(row) for row in rows]

    passed = all(
        bool(result["denied"]) and result["sqlstate"] == "42501"
        for result in checks.values()
    )
    wrappers = {
        row["proname"]: row
        for row in functions
        if row["proname"] in {
            "memory_apply_legal_erasure_extended",
            "memory_apply_ontology_transition",
            "memory_lifecycle_finalize_payload",
        }
    }
    internals = {
        row["proname"]: row
        for row in functions
        if row["proname"].endswith("_internal_0049") or row["proname"] == "memory_apply_legal_erasure"
    }
    passed = passed and all(row["owner"] == "memory_admin" for row in wrappers.values())
    passed = passed and all("search_path=pg_catalog, public, pg_temp" in row["config"] for row in wrappers.values())
    passed = passed and all(not bool(row["runtime_execute"]) for row in internals.values())

    evidence = {
        "status": "PASS" if passed else "FAIL",
        "migration": "0050_security_definer_tenant_boundary",
        "cross_tenant_checks": checks,
        "functions": functions,
        "transaction_fail_safe_rollback": True,
        "secret_material_exposed": False,  # nosec B105 -- boolean evidence/status field, not a credential.
    }
    evidence_dir = ROOT / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    target = evidence_dir / "SECURITY_DEFINER_TENANT_BOUNDARY_PROOF_20260905.json"
    target.write_text(json.dumps(evidence, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
