from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("MEMORY_PROJECT_ROOT", r"C:\New Projet\MEMORIA-PERMANENTE"))
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402

from memory_permanent.migration_runner import apply_migrations  # noqa: E402


def _dsn() -> str:
    value = os.getenv("MEMORY_ADMIN_DATABASE_URL", "").strip()
    if not value:
        raise SystemExit("MEMORY_ADMIN_DATABASE_URL is required")
    parsed = urlparse(value)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise SystemExit("administrative DSN must use PostgreSQL")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("administrative DSN must remain loopback-local")
    if parsed.password is not None:
        raise SystemExit("administrative DSN must not contain an inline password; use PGPASSFILE")
    return value


def main() -> int:
    dsn = _dsn()
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        row = conn.execute(
            "SELECT current_user, rolsuper FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
    if not row or str(row[0]) != "postgres" or not bool(row[1]):
        raise SystemExit("administrative migration connection must be postgres superuser")
    result = apply_migrations(dsn, ROOT / "migrations")
    print(json.dumps({
        "status": "APPLIED_OR_VERIFIED",
        "migration_count": len(result),
        "latest": result[-1]["version"] if result else None,
        "admin_identity": "postgres",
        "secret_material_exposed": False,  # nosec B105 -- boolean evidence/status field, not a credential.
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
