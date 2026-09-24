from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import sys
import uuid
from pathlib import Path

ROOT = Path(os.getenv("MEMORY_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "src"))

import psycopg  # noqa: E402

from memory_permanent.access_policy import AgentAccessContext  # noqa: E402
from memory_permanent.backup_crypto import BackupCryptoManager  # noqa: E402
from memory_permanent.canonical_mutation import canonical_mutation_scope  # noqa: E402
from memory_permanent.erasure_manager import ErasureManager  # noqa: E402
from memory_permanent.migration_runner import apply_migrations  # noqa: E402
from memory_permanent.runtime_preflight import verify_runtime_database  # noqa: E402
from memory_permanent.store import PostgresMemoryStore  # noqa: E402

TARGET = "memoria_permanente_v52_restoreproof"


def exe(pg_bin: Path, name: str) -> str:
    candidate = pg_bin / (name + (".exe" if os.name == "nt" else ""))
    return str(candidate if candidate.exists() else name)


def run(cmd: list[str], env: dict[str, str], *, capture: bool=False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, env=env, text=True, capture_output=capture, check=True, encoding="utf-8", errors="replace")  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.


def scalar(dsn: str, sql: str) -> str:
    with psycopg.connect(dsn,connect_timeout=5) as conn:
        return str(conn.execute(sql).fetchone()[0])


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("manifest"); args=ap.parse_args()
    manifest=Path(args.manifest).resolve()
    if not manifest.is_file(): raise SystemExit("encrypted backup manifest missing")
    pg_bin=Path(os.getenv("MEMORY_PG_BIN", ROOT/"runtime"/"pgsql18-bin"/"pgsql"/"bin"))
    admin_pass=Path(os.getenv("MEMORY_ADMIN_PGPASSFILE", ROOT/"runtime"/"secrets"/"postgres.pgpass.conf"))
    app_pass=Path(os.getenv("MEMORY_APP_PGPASSFILE", ROOT/"runtime"/"secrets"/"pgpass.conf"))
    if not admin_pass.is_file() or not app_pass.is_file(): raise SystemExit("restore passfiles missing")
    work=ROOT/"runtime"/"recovery-proof"; work.mkdir(parents=True,exist_ok=True)
    tmp=work/("restore-"+uuid.uuid4().hex+".dump.tmp")
    manager=BackupCryptoManager(); man=manager.read_manifest(manifest)
    admin_env=os.environ.copy(); admin_env["PGPASSFILE"]=str(admin_pass)
    app_env=os.environ.copy(); app_env["PGPASSFILE"]=str(app_pass)
    admin_dsn=f"postgresql://postgres@127.0.0.1:55436/{TARGET}"
    app_dsn=f"postgresql://memory_app@127.0.0.1:55436/{TARGET}"
    try:
        manager.decrypt_backup(manifest_path=manifest,output_path=tmp)
        run([exe(pg_bin,"pg_restore"),"--list",str(tmp)],admin_env,capture=True)
        run([exe(pg_bin,"dropdb"),"-w","-h","127.0.0.1","-p","55436","-U","postgres","--if-exists","--force",TARGET],admin_env)
        run([exe(pg_bin,"createdb"),"-w","-h","127.0.0.1","-p","55436","-U","postgres","-O","postgres","-E","UTF8","-T","template0",TARGET],admin_env)
        run([exe(pg_bin,"pg_restore"),"-w","-h","127.0.0.1","-p","55436","-U","postgres","-d",TARGET,"--exit-on-error",str(tmp)],admin_env)
        # Recovery may start from a pre-promotion backup. Migrate under the admin
        # plane before any runtime identity or traffic is allowed.
        os.environ["PGPASSFILE"]=str(admin_pass)
        migrations=apply_migrations(admin_dsn, ROOT/"migrations")
        with psycopg.connect(admin_dsn,connect_timeout=5) as conn:
            conn.execute("INSERT INTO schema_meta(key,value) VALUES('restore_erasure_replay_status','PENDING') ON CONFLICT(key) DO UPDATE SET value='PENDING',updated_at=now()")
        run([exe(pg_bin,"pg_amcheck"),"-w","-h","127.0.0.1","-p","55436","-U","postgres","-d",TARGET,"--install-missing"],admin_env)
        os.environ["PGPASSFILE"]=str(app_pass)
        preflight=verify_runtime_database(app_dsn)
        store=PostgresMemoryStore(app_dsn,initialize=False,tenant_id="LEGACY",access=AgentAccessContext.system())
        audit=store.verify_audit_chain()
        if not audit.get("ok"): raise RuntimeError("restored audit chain invalid")
        # P18 restore contract: replay external erasure ledger before the restored DB may serve traffic.
        with canonical_mutation_scope("recovery-integrity-agent","legal_erasure.replay"):
            replay=ErasureManager(store).replay(source_ref=str(manifest),actor="recovery-integrity-agent")
        if replay.get("result") != "PASS": raise RuntimeError("erasure replay failed")
        os.environ["PGPASSFILE"]=str(admin_pass)
        with psycopg.connect(admin_dsn,connect_timeout=5) as conn:
            conn.execute("INSERT INTO schema_meta(key,value) VALUES('restore_erasure_replay_status','PASS') ON CONFLICT(key) DO UPDATE SET value='PASS',updated_at=now()")
        os.environ["PGPASSFILE"]=str(app_pass)
        result={
            "status":"PASS","target_database":TARGET,"backup_id":man["backup_id"],
            "pg_amcheck":"PASS","migration_count_after_restore":len(migrations),"runtime_preflight":preflight,"audit_chain_ok":True,
            "audit_events":audit.get("events"),"erasure_replay":replay,"restore_flow":["RESTORE","MIGRATE","ERASURE_REPLAY","VERIFY"],
            "plaintext_restore_temp_retained":False,"secret_material_exposed":False,  # nosec B105 -- boolean evidence/status field, not a credential.
        }
        print(json.dumps(result,sort_keys=True,default=str)); return 0
    finally:
        tmp.unlink(missing_ok=True)
        os.environ.pop("PGPASSFILE",None)

if __name__=="__main__": raise SystemExit(main())
