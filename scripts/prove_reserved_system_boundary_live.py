from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "RESERVED_SYSTEM_BOUNDARY_LIVE_PROOF_20260906.json"
DSN = os.getenv("MEMORY_DATABASE_URL", "postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary")


def _attempt(sql: str, params: tuple[object, ...] = ()) -> dict[str, object]:
    with psycopg.connect(DSN, connect_timeout=5) as conn:
        conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',true)")
        conn.execute("SELECT set_config('app.current_agent','__SYSTEM__',true)")
        try:
            conn.execute(sql, params)
        except psycopg.Error as exc:
            conn.rollback()
            return {"denied": True, "sqlstate": exc.sqlstate, "error_type": type(exc).__name__}
        conn.rollback()
        return {"denied": False, "sqlstate": None, "error_type": None}


def main() -> int:
    now = datetime.now(UTC)
    item_id = "mem-audit-system-" + hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:24]
    insert = _attempt(
        """INSERT INTO memory_items(item_id,namespace,memory_key,category,content_json,content_text,provenance,confidence,source,tags,valid_from,content_sha256,tenant_id,sharing_scope,memory_scope,occurred_at,observed_at) VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (item_id,"AUDIT_SYSTEM_BOUNDARY","reserved-system-write","FACT","{}","must never persist","{}",1.0,"security-audit",[],now,"0"*64,"LEGACY","SYSTEM_SHARED","GLOBAL_USER",now,now),
    )
    gate = _attempt("SELECT memory_set_runtime_gate(%s,%s)", ("restore_erasure_replay_status", "PASS"))
    with psycopg.connect(DSN, row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',true)")
        conn.execute("SELECT set_config('app.current_agent','__SYSTEM__',true)")
        visible = int(conn.execute("SELECT count(*) AS n FROM memory_items").fetchone()["n"])
        role = dict(conn.execute("SELECT current_user AS role,r.rolsuper,r.rolbypassrls FROM pg_roles r WHERE r.rolname=current_user").fetchone())
        fn = dict(conn.execute("""SELECT pg_get_userbyid(p.proowner) AS owner,has_function_privilege('memory_app',p.oid,'EXECUTE') AS runtime_execute,coalesce(array_to_string(p.proconfig,','),'') AS config FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname='memory_set_runtime_gate'""").fetchone())
        latest = str(conn.execute("SELECT version FROM schema_migrations ORDER BY applied_at DESC,version DESC LIMIT 1").fetchone()["version"])
        persisted = int(conn.execute("SELECT count(*) AS n FROM memory_items WHERE item_id=%s", (item_id,)).fetchone()["n"])
    checks = {
        "runtime_role_is_memory_app": role["role"] == "memory_app",
        "runtime_not_superuser": role["rolsuper"] is False,
        "runtime_no_bypassrls": role["rolbypassrls"] is False,
        "system_context_reads_no_rows": visible == 0,
        "system_context_insert_denied_42501": insert["denied"] is True and insert["sqlstate"] == "42501",
        "restore_gate_denied_42501": gate["denied"] is True and gate["sqlstate"] == "42501",
        "probe_row_not_persisted": persisted == 0,
        "gate_owner_memory_admin": fn["owner"] == "memory_admin",
        "gate_search_path_hardened": "search_path=pg_catalog, public, pg_temp" in str(fn["config"]),
        "latest_migration_0051": latest == "0051_reserved_system_and_restore_gate_hardening",
    }
    failed = [name for name, ok in checks.items() if not ok]
    proof = {"status":"PASS" if not failed else "FAIL","checks":checks,"failed":failed,"system_visible_rows":visible,"insert_attempt":insert,"restore_gate_attempt":gate,"runtime_role":role,"runtime_gate":fn,"latest_migration":latest,"secret_material_exposed":False,"generated_at":datetime.now(UTC).isoformat()}  # nosec B105 -- boolean evidence/status field, not a credential.
    EVIDENCE.write_text(json.dumps(proof, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({"status":proof["status"],"failed":failed,"evidence":str(EVIDENCE)}, sort_keys=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
