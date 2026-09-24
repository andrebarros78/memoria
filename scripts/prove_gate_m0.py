from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory_permanent.migration_runner import migration_status  # noqa: E402
from memory_permanent.store import (  # noqa: E402
    IdempotencyConflict,
    PostgresMemoryStore,
)


def dsn_from_pgpass() -> str:
    pgpass = Path(os.getenv("PGPASSFILE", str(Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "MemoriaPermanente" / "postgres" / "pgpass.conf")))
    raw = pgpass.read_text(encoding="ascii").strip()
    host, port, database, user, password = raw.split(":", 4)
    return f"host={host} port={port} dbname={database} user={user} password={password} connect_timeout=5"


def blocked_mutation(dsn: str, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
    try:
        with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as conn:
            conn.execute("SELECT set_config('app.current_tenant', %s, true)", ("LEGACY",))
            with conn.transaction():
                conn.execute(sql, params)
        return {"blocked": False, "error": None}
    except psycopg.Error as exc:
        return {"blocked": True, "sqlstate": exc.sqlstate, "error_type": type(exc).__name__, "error": str(exc).splitlines()[0]}


def main() -> int:
    dsn = dsn_from_pgpass()
    suffix = f"{int(datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}"
    store = PostgresMemoryStore(dsn)
    migrations = migration_status(dsn)
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("SELECT set_config('app.current_tenant', %s, true)", ("LEGACY",))
        before = conn.execute("SELECT count(*) AS n FROM memory_items").fetchone()["n"]
        postgres_version = conn.execute("SHOW server_version").fetchone()["server_version"]
        schema_version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()["value"]

    idem_create = f"m0-create-{suffix}"
    content_v1 = {"gate": "M0", "value": "canonical-v1", "suffix": suffix}
    common = dict(
        namespace="SYSTEM",
        memory_key=f"gate.m0.{suffix}",
        content=content_v1,
        content_text=f"Gate M0 canonical persistence proof {suffix} version one",
        provenance={"trusted": True, "proof": "GATE_M0", "suffix": suffix},
        confidence=1.0,
        source="sovereign-system",
        category="EVIDENCE",
        source_version="M0-v1",
        tags=["GATE_M0", "CANONICAL"],
        changed_by="prove_gate_m0",
        idempotency_key=idem_create,
    )
    item_id = store.remember(**common)
    replay_item_id = store.remember(**common)
    create_conflict = False
    try:
        store.remember(**{**common, "content": {**content_v1, "value": "different"}})
    except IdempotencyConflict:
        create_conflict = True

    idem_revise = f"m0-revise-{suffix}"
    revise_kwargs = dict(
        content={"gate": "M0", "value": "canonical-v2", "suffix": suffix},
        content_text=f"Gate M0 canonical persistence proof {suffix} version two",
        provenance={"trusted": True, "proof": "GATE_M0", "suffix": suffix, "revision": 2},
        confidence=1.0,
        source="sovereign-system",
        source_version="M0-v2",
        tags=["GATE_M0", "CANONICAL", "VERSION_2"],
        changed_by="prove_gate_m0",
        idempotency_key=idem_revise,
    )
    revision = store.revise(item_id, **revise_kwargs)
    revision_replay = store.revise(item_id, **revise_kwargs)
    revise_conflict = False
    try:
        store.revise(item_id, **{**revise_kwargs, "content_text": "different replay payload"})
    except IdempotencyConflict:
        revise_conflict = True

    versions = store.list_versions(item_id)
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("SELECT set_config('app.current_tenant', %s, true)", ("LEGACY",))
        event_rows = conn.execute(
            "SELECT event_id,event_type,version_id,request_sha256,created_at FROM memory_events WHERE item_id=%s ORDER BY event_seq",
            (item_id,),
        ).fetchall()
        idem_rows = conn.execute(
            "SELECT operation,idempotency_key,request_sha256,response_json FROM idempotency_records WHERE idempotency_key=ANY(%s) ORDER BY operation",
            ([idem_create, idem_revise],),
        ).fetchall()
        after = conn.execute("SELECT count(*) AS n FROM memory_items").fetchone()["n"]
        row = conn.execute("SELECT content_sha256,content_text FROM memory_items WHERE item_id=%s", (item_id,)).fetchone()

    version_id = str(versions[-1]["version_id"])
    event_id = str(event_rows[-1]["event_id"])
    append_only = {
        "memory_versions_update": blocked_mutation(dsn, "UPDATE memory_versions SET content_text=content_text WHERE version_id=%s", (version_id,)),
        "memory_versions_delete": blocked_mutation(dsn, "DELETE FROM memory_versions WHERE version_id=%s", (version_id,)),
        "memory_events_update": blocked_mutation(dsn, "UPDATE memory_events SET event_type=event_type WHERE event_id=%s", (event_id,)),
        "memory_events_delete": blocked_mutation(dsn, "DELETE FROM memory_events WHERE event_id=%s", (event_id,)),
    }
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("SELECT set_config('app.current_tenant', %s, true)", ("LEGACY",))
        audit_row = conn.execute("SELECT seq FROM audit_events WHERE target_id=%s ORDER BY seq DESC LIMIT 1", (item_id,)).fetchone()
    if not audit_row:
        raise RuntimeError("audit event for M0 proof missing")
    audit_seq = int(audit_row["seq"])
    append_only["audit_events_update"] = blocked_mutation(dsn, "UPDATE audit_events SET target_id=target_id WHERE seq=%s", (audit_seq,))
    append_only["audit_events_delete"] = blocked_mutation(dsn, "DELETE FROM audit_events WHERE seq=%s", (audit_seq,))
    audit = store.verify_audit_chain()

    migration_versions = [m["version"] for m in migrations]
    checks = {
        "POSTGRESQL_LIVE": bool(postgres_version),
        "MIGRATIONS_VERSIONED": migration_versions[:2] == ["0001_base", "0002_m0_canonical"],
        "MIGRATION_CHECKSUMS_PRESENT": all(len(m["checksum_sha256"]) == 64 for m in migrations[:2]),
        "SCHEMA_VERSION_SUPPORTS_M0": str(schema_version).startswith("memory-") and tuple(int(x) for x in str(schema_version).split("-", 1)[1].split(".")) >= (0, 2, 0),
        "IDEMPOTENT_CREATE_REPLAY": item_id == replay_item_id,
        "IDEMPOTENT_CREATE_CONFLICT_REJECTED": create_conflict,
        "IDEMPOTENT_REVISION_REPLAY": revision == revision_replay,
        "IDEMPOTENT_REVISION_CONFLICT_REJECTED": revise_conflict,
        "ONE_MEMORY_CREATED": int(after) == int(before) + 1,
        "TWO_CANONICAL_VERSIONS": len(versions) == 2 and [int(v["version_no"]) for v in versions] == [1, 2],
        "VERSION_CHAIN_LINKED": versions[1]["previous_version_id"] == versions[0]["version_id"],
        "TWO_APPEND_ONLY_MEMORY_EVENTS": len(event_rows) == 2 and [e["event_type"] for e in event_rows] == ["MEMORY_CREATED", "MEMORY_REVISED"],
        "TWO_IDEMPOTENCY_RECORDS": len(idem_rows) == 2,
        "CURRENT_PROJECTION_IS_V2": str(row["content_text"]).endswith("version two") and str(row["content_sha256"]) == str(versions[-1]["content_sha256"]),
        "APPEND_ONLY_DB_ENFORCEMENT": all(v["blocked"] for v in append_only.values()),
        "AUDIT_CHAIN_VALID": bool(audit.get("ok")),
    }
    failed = [k for k, v in checks.items() if not v]
    result = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "gate": "M0",
        "postgres_version": str(postgres_version),
        "schema_version": str(schema_version),
        "migrations": migrations,
        "item_id": item_id,
        "versions": versions,
        "memory_events": [
            {**dict(e), "created_at": e["created_at"].isoformat()} for e in event_rows
        ],
        "idempotency_records": [dict(r) for r in idem_rows],
        "append_only_attempts": append_only,
        "audit": audit,
        "checks": checks,
        "failed_checks": failed,
        "GATE_M0": "PASS" if not failed else "FAIL",
        "CANONICAL_PERSISTENCE_PROVEN": not failed,
    }
    proof_json = ROOT / "evidence" / "M0_GATE_PROOF.json"
    proof_md = ROOT / "evidence" / "M0_GATE_PROOF.md"
    proof_json.parent.mkdir(parents=True, exist_ok=True)
    proof_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Gate M0 â€” PersistÃªncia canÃ´nica",
        "",
        f"**GATE_M0:** {result['GATE_M0']}",
        f"**CANONICAL_PERSISTENCE_PROVEN:** {result['CANONICAL_PERSISTENCE_PROVEN']}",
        "",
        f"PostgreSQL: {postgres_version}",
        f"Schema: {schema_version}",
        f"Proof item: {item_id}",
        "",
        "## Checks",
    ] + [f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in checks.items()]
    proof_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "GATE_M0": result["GATE_M0"],
        "item_id": item_id,
        "migration_versions": migration_versions,
        "version_count": len(versions),
        "event_count": len(event_rows),
        "idempotency_count": len(idem_rows),
        "append_only_blocked": all(v["blocked"] for v in append_only.values()),
        "audit_ok": audit.get("ok"),
        "failed": failed,
    }, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())


