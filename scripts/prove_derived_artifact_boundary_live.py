from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import errors

ROOT = Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0")
EVIDENCE = ROOT / "evidence" / "DERIVED_ARTIFACT_BOUNDARY_LIVE_PROOF_20260905.json"
EVIDENCE_MD = ROOT / "evidence" / "DERIVED_ARTIFACT_BOUNDARY_LIVE_PROOF_20260905.md"
DSN = "postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary"


def expect_insufficient_privilege(sql: str, label: str) -> dict[str, object]:
    try:
        with psycopg.connect(DSN, connect_timeout=5) as conn:
            with conn.transaction():
                conn.execute(sql)
    except errors.InsufficientPrivilege as exc:
        return {
            "name": label,
            "pass": True,  # nosec B105 -- boolean evidence/status field, not a credential.
            "sqlstate": exc.sqlstate,
            "error_type": type(exc).__name__,
        }
    return {"name": label, "pass": False, "sqlstate": None, "error_type": "NO_DENIAL"}  # nosec B105 -- boolean evidence/status field, not a credential.


def main() -> int:
    if not os.getenv("PGPASSFILE"):
        raise SystemExit("PGPASSFILE is required")

    with psycopg.connect(DSN, connect_timeout=5) as conn:
        with conn.transaction():
            conn.execute("SELECT set_config('app.current_tenant','LEGACY',true)")
            privilege_row = conn.execute(
                """SELECT
                     has_table_privilege(current_user,'memory_derived_artifacts','INSERT'),
                     has_table_privilege(current_user,'memory_derived_artifacts','UPDATE'),
                     has_table_privilege(current_user,'memory_derived_artifacts','SELECT'),
                     has_function_privilege(current_user,'memory_upsert_derived_artifact(text,text,text,text,text,jsonb,text,text[])','EXECUTE')"""
            ).fetchone()
            role_row = conn.execute(
                "SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname='memory_admin'"
            ).fetchone()
            migration_row = conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()

    checks = [
        {
            "name": "runtime_privilege_matrix",
            "pass": bool(privilege_row)
            and tuple(bool(value) for value in privilege_row) == (False, False, True, True),
            "actual": list(privilege_row) if privilege_row else None,
            "expected": [False, False, True, True],
        },
        {
            "name": "security_definer_owner_non_privileged",
            "pass": bool(role_row) and not bool(role_row[1]) and not bool(role_row[2]),
            "actual": list(role_row) if role_row else None,
        },
        expect_insufficient_privilege(
            """SELECT set_config('app.current_tenant','LEGACY',true);
               INSERT INTO memory_derived_artifacts(
                 artifact_id,tenant_id,artifact_type,artifact_ref,status,metadata
               ) VALUES(
                 'art-0000000000000000000000000000000000000000','LEGACY',
                 'CHECKPOINT','direct-insert-must-fail','READY','{}'::jsonb
               )""",
            "direct_insert_denied",
        ),
        expect_insufficient_privilege(
            """SELECT set_config('app.current_tenant','LEGACY',true);
               UPDATE memory_derived_artifacts SET updated_at=updated_at WHERE false""",
            "direct_update_denied",
        ),
        expect_insufficient_privilege(
            """SELECT set_config('app.current_tenant','__SYSTEM__',true);
               SELECT memory_upsert_derived_artifact(
                 'art-0000000000000000000000000000000000000000',
                 'CHECKPOINT','system-tenant-must-fail',NULL,'READY','{}'::jsonb,NULL,
                 ARRAY['missing-source-version']::text[]
               )""",
            "memory_app_system_tenant_denied",
        ),
    ]

    failed = [check["name"] for check in checks if not check["pass"]]
    proof = {
        "gate": "DERIVED_ARTIFACT_RUNTIME_BOUNDARY",
        "result": "PASS" if not failed else "FAIL",
        "generated_at": datetime.now(UTC).isoformat(),
        "database_role": "memory_app",
        "latest_migration": migration_row[0] if migration_row else None,
        "checks": checks,
        "failed": failed,
        "secret_material_exposed": False,  # nosec B105 -- boolean evidence/status field, not a credential.
    }
    EVIDENCE.write_text(json.dumps(proof, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Derived Artifact Runtime Boundary — Live Proof",
        "",
        f"Result: **{proof['result']}**",
        "",
        f"Latest migration: `{proof['latest_migration']}`",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for check in checks:
        lines.append(f"| {check['name']} | {'PASS' if check['pass'] else 'FAIL'} |")
    EVIDENCE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"result": proof["result"], "failed": failed, "evidence": str(EVIDENCE)}))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
