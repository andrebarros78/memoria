from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
DSN = os.getenv(
    "MEMORY_DATABASE_URL",
    "postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary",
)


def main() -> int:
    evidence: dict[str, object] = {
        "secret_material_exposed": False,  # nosec B105 -- boolean evidence/status field, not a credential.
        "runtime_role": "memory_app",
    }

    with psycopg.connect(DSN, row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("BEGIN READ ONLY")
        conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',true)")
        evidence["reserved_system_visible_items"] = int(
            conn.execute("SELECT count(*) AS n FROM memory_items").fetchone()["n"]
        )
        conn.execute("SELECT set_config('app.current_agent','__SYSTEM__',true)")
        evidence["reserved_system_agent_bypass"] = bool(
            conn.execute(
                "SELECT memory_agent_visible('AGENT_PRIVATE',NULL,'other-agent',NULL,NULL,NULL) AS allowed"
            ).fetchone()["allowed"]
        )
        conn.rollback()

    with psycopg.connect(DSN, row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("BEGIN")
        conn.execute("SELECT set_config('app.current_tenant','LEGACY',true)")
        try:
            conn.execute("SELECT memory_set_runtime_gate('restore_erasure_replay_status','PASS')")
            evidence["runtime_restore_gate_denied"] = False
            evidence["runtime_restore_gate_sqlstate"] = None
        except psycopg.Error as exc:
            evidence["runtime_restore_gate_denied"] = True
            evidence["runtime_restore_gate_sqlstate"] = exc.sqlstate
        conn.rollback()

    with psycopg.connect(DSN, row_factory=dict_row, connect_timeout=5) as conn:
        evidence["latest_migration"] = str(
            conn.execute("SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1").fetchone()["version"]
        )
        evidence["runtime_gate_owner"] = str(
            conn.execute(
                "SELECT pg_get_userbyid(p.proowner) AS owner FROM pg_proc p "
                "WHERE p.oid='public.memory_set_runtime_gate(text,text)'::regprocedure"
            ).fetchone()["owner"]
        )
        evidence["runtime_gate_execute"] = bool(
            conn.execute(
                "SELECT has_function_privilege('memory_app','public.memory_set_runtime_gate(text,text)','EXECUTE') AS allowed"
            ).fetchone()["allowed"]
        )

    passed = (
        evidence["reserved_system_visible_items"] == 0
        and evidence["reserved_system_agent_bypass"] is False
        and evidence["runtime_restore_gate_denied"] is True
        and evidence["runtime_restore_gate_sqlstate"] == "42501"
        and evidence["latest_migration"] == "0051_reserved_system_and_restore_gate_hardening"
        and evidence["runtime_gate_owner"] == "memory_admin"
        and evidence["runtime_gate_execute"] is True
    )
    evidence["status"] = "PASS" if passed else "FAIL"

    target = ROOT / "evidence" / "RESERVED_SYSTEM_RESTORE_GATE_LIVE_PROOF_20260905.json"
    target.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(evidence, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
