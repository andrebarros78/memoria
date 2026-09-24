from __future__ import annotations

import hashlib
import sysconfig
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


class MigrationDriftError(RuntimeError):
    pass


def default_migrations_dir() -> Path:
    source_path = Path(__file__).resolve().parents[2] / "migrations"
    if source_path.is_dir():
        return source_path
    target_path = Path(__file__).resolve().parents[1] / "share" / "memoria-permanente" / "migrations"
    if target_path.is_dir():
        return target_path
    installed_path = Path(sysconfig.get_path("data")) / "share" / "memoria-permanente" / "migrations"
    if installed_path.is_dir():
        return installed_path
    raise FileNotFoundError("MEMORIA-PERMANENTE migrations are not installed")


def _set_system_tenant(conn: Any) -> None:
    """Run schema migrations with the explicit system tenant under FORCE RLS."""
    conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',true)")


def migration_files(root: Path) -> list[Path]:
    return sorted(p for p in root.glob("*.sql") if p.is_file())


def apply_migrations(dsn: str, migrations_dir: Path) -> list[dict[str, Any]]:
    migrations_dir = migrations_dir.resolve()
    if not migrations_dir.exists():
        raise FileNotFoundError(f"migrations directory not found: {migrations_dir}")
    results: list[dict[str, Any]] = []
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as conn:
        with conn.transaction():
            _set_system_tenant(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations(
                  version text PRIMARY KEY,
                  filename text NOT NULL,
                  checksum_sha256 text NOT NULL,
                  applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
        for path in migration_files(migrations_dir):
            version = path.stem
            raw = path.read_bytes()
            checksum = hashlib.sha256(raw).hexdigest()
            sql = raw.decode("utf-8")
            with conn.transaction():
                _set_system_tenant(conn)
                existing = conn.execute(
                    "SELECT version,filename,checksum_sha256,applied_at FROM schema_migrations WHERE version=%s",
                    (version,),
                ).fetchone()
                if existing:
                    if str(existing["checksum_sha256"]) != checksum:
                        raise MigrationDriftError(f"checksum drift for {version}")
                    results.append({"version": version, "status": "ALREADY_APPLIED", "checksum_sha256": checksum})
                    continue
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO schema_migrations(version,filename,checksum_sha256) VALUES(%s,%s,%s)",
                    (version, path.name, checksum),
                )
                results.append({"version": version, "status": "APPLIED", "checksum_sha256": checksum})
    return results


def migration_status(dsn: str) -> list[dict[str, Any]]:
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as conn:
        rows = conn.execute(
            "SELECT version,filename,checksum_sha256,applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
    return [
        {
            "version": str(row["version"]),
            "filename": str(row["filename"]),
            "checksum_sha256": str(row["checksum_sha256"]),
            "applied_at": row["applied_at"].isoformat(),
        }
        for row in rows
    ]
