from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(os.getenv("MEMORY_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402

from memory_permanent.backup_crypto import (  # noqa: E402
    BackupCryptoManager,
    sha256_file,
)

DB_RE = re.compile(r"^memoria_permanente_v52_(?:primary|hardening)$")


def exe(pg_bin: Path, name: str) -> str:
    candidate = pg_bin / (name + (".exe" if os.name == "nt" else ""))
    return str(candidate if candidate.exists() else name)


def run(cmd: list[str], env: dict[str, str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, env=env, text=True, capture_output=capture, check=True, encoding="utf-8", errors="replace")  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database", default=os.getenv("MEMORY_BACKUP_DATABASE", "memoria_permanente_v52_primary"))
    ap.add_argument("--output-dir", default="")
    args = ap.parse_args()
    database = str(args.database).strip()
    if not DB_RE.fullmatch(database):
        raise SystemExit("backup database is outside the V5.2 allowlist")
    pg_bin = Path(os.getenv("MEMORY_PG_BIN", ROOT / "runtime" / "pgsql18-bin" / "pgsql" / "bin"))
    pgpass = Path(os.getenv("PGPASSFILE", ""))
    if not pgpass.is_file():
        raise SystemExit("PGPASSFILE is required; plaintext/inlined database credentials are forbidden")
    output = Path(args.output_dir) if args.output_dir else ROOT / "backups" / "v52-encrypted"
    output.mkdir(parents=True, exist_ok=True)
    backup_id = "v52-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    dump = output / f"{backup_id}.dump.tmp"
    encrypted = output / f"{backup_id}.mpb"
    manifest = output / f"{backup_id}.encrypted.manifest.json"
    env = os.environ.copy()
    env["PGPASSFILE"] = str(pgpass)
    admin_dsn = f"postgresql://postgres@127.0.0.1:55436/{database}"
    if "password=" in admin_dsn.lower() or "@" not in admin_dsn:
        raise SystemExit("invalid non-secret administrative DSN")
    try:
        run([exe(pg_bin,"pg_dump"),"-w","-h","127.0.0.1","-p","55436","-U","postgres","-d",database,"-Fc","-f",str(dump)], env)
        catalog = run([exe(pg_bin,"pg_restore"),"--list",str(dump)], env, capture=True).stdout.splitlines()
        with psycopg.connect(admin_dsn, connect_timeout=5) as conn:
            server = str(conn.execute("SELECT current_setting('server_version')").fetchone()[0])
            vector = str(conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0])
            migration_count = int(conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0])
            latest = str(conn.execute("SELECT version FROM schema_migrations ORDER BY applied_at DESC,version DESC LIMIT 1").fetchone()[0])
        manager = BackupCryptoManager()
        manager.encrypt_dump(
            dump_path=dump, encrypted_path=encrypted, manifest_path=manifest, backup_id=backup_id,
            generated_at=datetime.now(UTC), metadata={
                "database": database, "pg_dump_version": run([exe(pg_bin,"pg_dump"),"--version"],env,capture=True).stdout.strip(),
                "restore_catalog_entries": sum(1 for line in catalog if line and not line.startswith(";")),
                "purpose": "V5.2_SOVEREIGN_ENCRYPTED_BACKUP", "backup_policy": "BKP-V5.2-2.0.0",
                "acl_preserved": True, "owner_preserved": True, "postgresql": server, "pgvector": vector,
                "migration_count": migration_count, "latest_migration": latest,
            },
        )
        dump.unlink(missing_ok=True)
        if dump.exists() or not encrypted.is_file() or not manifest.is_file():
            raise RuntimeError("encrypted backup finalization invariant failed")
        verified = manager.read_manifest(manifest)
        result = {
            "status": "PASS", "backup_id": backup_id, "database": database,
            "encrypted_path": str(encrypted), "manifest_path": str(manifest),
            "cipher": verified["cipher"], "ciphertext_sha256": sha256_file(encrypted),
            "manifest_authenticated": True, "plaintext_retained": dump.exists(),
            "acl_preserved": True, "owner_preserved": True, "migration_count": migration_count,
            "latest_migration": latest, "secret_material_exposed": False,  # nosec B105 -- boolean evidence/status field, not a credential.
        }
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        # Fail closed: a failed backup attempt must not leave a new plaintext dump behind.
        dump.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
