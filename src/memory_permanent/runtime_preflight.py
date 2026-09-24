from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import psycopg

from .migration_runner import default_migrations_dir, migration_files, migration_status


def expected_migration_hashes(root: Path | None = None) -> dict[str, str]:
    base = root or default_migrations_dir()
    return {p.stem: hashlib.sha256(p.read_bytes()).hexdigest() for p in migration_files(base)}


def verify_migration_parity(applied: list[dict[str, Any]], expected: dict[str, str]) -> dict[str, Any]:
    actual = {str(row["version"]): str(row["checksum_sha256"]) for row in applied}
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    drift = sorted(k for k in set(expected) & set(actual) if expected[k] != actual[k])
    if missing or extra or drift:
        raise RuntimeError(f"migration parity failed: missing={missing} extra={extra} drift={drift}")
    return {"migration_count": len(expected), "latest_migration": sorted(expected)[-1] if expected else None}


def verify_runtime_database(dsn: str) -> dict[str, Any]:
    parity = verify_migration_parity(migration_status(dsn), expected_migration_hashes())
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        server_row = conn.execute("SELECT current_setting('server_version')").fetchone()
        if server_row is None:
            raise RuntimeError("runtime database server version cannot be resolved")
        server = str(server_row[0])
        vector_row = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
        role_row = conn.execute(
            "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
            "FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
    if not role_row:
        raise RuntimeError("runtime database role cannot be resolved")
    role_name = str(role_row[0])
    privileged = any(bool(value) for value in role_row[1:])
    if privileged:
        raise RuntimeError(f"privileged database role is forbidden for runtime: {role_name}")
    if not server.startswith("18."):
        raise RuntimeError(f"unsupported PostgreSQL runtime: {server}")
    vector = str(vector_row[0]) if vector_row else ""
    if not vector:
        raise RuntimeError("pgvector extension is missing")
    try:
        vector_parts = tuple(int(part) for part in vector.split(".")[:3])
    except ValueError as exc:
        raise RuntimeError(f"invalid pgvector version: {vector}") from exc
    if vector_parts < (0, 8, 6):
        raise RuntimeError(f"unsupported pgvector runtime: {vector}; minimum is 0.8.6")
    return {
        **parity,
        "postgresql": server,
        "pgvector": vector,
        "database_role": role_name,
        "database_role_privileged": False,
        "status": "READY",
    }


def main() -> int:
    dsn = os.environ.get("MEMORY_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("MEMORY_DATABASE_URL is required")
    print(json.dumps(verify_runtime_database(dsn), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
