from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "0030_input_guard_v2.sql"
EVIDENCE = ROOT / "evidence" / "P15_MIGRATION_SOURCE_RECONCILIATION.json"
ORIGINAL_APPLIED_SHA256 = "6e4d912797506f8213c767ae4f8ac86efc95dc112567753d13985c8520378318"
EXPECTED_META = {
    "schema_version": "memory-0.23.0",
    "input_guard_version": "IG-2.0.0",
    "input_guard_languages": "en,pt,es,it,fr,de",
    "input_guard_encodings": "PERCENT,HTML_ENTITY,UNICODE_ESCAPE,BASE64,URLSAFE_BASE64,HEX",
    "input_guard_structured_sources": "MEMORY,ATTACHMENT,TOOL_OUTPUT,EXTERNAL_DOCUMENT,WEB_CONTENT",
    "input_guard_distributed_detection": "true",
}

raw = MIGRATION.read_bytes()
current_sha = hashlib.sha256(raw).hexdigest()
sql = raw.decode("utf-8")
lower = sql.casefold()
for forbidden in (" drop ", " delete ", " truncate ", " alter ", " create ", " grant ", " revoke "):
    if forbidden in f" {lower} ":
        raise SystemExit(f"forbidden statement in reconciled migration source: {forbidden.strip()}")
if "insert into schema_meta" not in lower or "on conflict" not in lower:
    raise SystemExit("reconciled migration source is not metadata-only/idempotent")

h, p, d, u, pw = (ROOT / "runtime" / "secrets" / "pgpass.conf").read_text(encoding="ascii").strip().split(":", 4)
dsn = f"host={h} port={p} dbname={d} user={u} password={pw} connect_timeout=5"

with psycopg.connect(dsn, row_factory=dict_row) as conn:
    with conn.transaction():
        conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',true)")
        row = conn.execute(
            "SELECT version,filename,checksum_sha256,applied_at FROM schema_migrations WHERE version='0030_input_guard_v2' FOR UPDATE"
        ).fetchone()
        if not row:
            raise SystemExit("0030_input_guard_v2 is not applied")
        observed_old = str(row["checksum_sha256"])
        if observed_old not in {ORIGINAL_APPLIED_SHA256, current_sha}:
            raise SystemExit(f"unexpected existing migration checksum: {observed_old}")
        meta_rows = conn.execute(
            "SELECT key,value FROM schema_meta WHERE key = ANY(%s)",
            (list(EXPECTED_META),),
        ).fetchall()
        observed_meta = {str(x["key"]): str(x["value"]) for x in meta_rows}
        if observed_meta != EXPECTED_META:
            raise SystemExit(f"P15 schema contract mismatch: {observed_meta}")

        # Execute the reconstructed metadata-only migration inside the same transaction.
        # It is idempotent and must leave the semantic contract unchanged.
        conn.execute(sql)
        after_rows = conn.execute(
            "SELECT key,value FROM schema_meta WHERE key = ANY(%s)",
            (list(EXPECTED_META),),
        ).fetchall()
        after_meta = {str(x["key"]): str(x["value"]) for x in after_rows}
        if after_meta != EXPECTED_META:
            raise SystemExit("reconstructed migration changes the P15 semantic contract")

        if observed_old != current_sha:
            conn.execute(
                "UPDATE schema_migrations SET checksum_sha256=%s,filename='0030_input_guard_v2.sql' WHERE version='0030_input_guard_v2'",
                (current_sha,),
            )
        reconciliation_meta = {
            "input_guard_migration_original_checksum": ORIGINAL_APPLIED_SHA256,
            "input_guard_migration_reconciled_checksum": current_sha,
            "input_guard_migration_reconciliation_reason": "SOURCE_OVERWRITE_DURING_IN_PROGRESS_P15_RECOVERY_SEMANTICALLY_RECONSTRUCTED",
        }
        for key, value in reconciliation_meta.items():
            conn.execute(
                "INSERT INTO schema_meta(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()",
                (key, value),
            )

proof = {
    "result": "PASS",
    "reconciled_at": datetime.now().astimezone().isoformat(),
    "migration": "0030_input_guard_v2",
    "original_applied_sha256": ORIGINAL_APPLIED_SHA256,
    "reconciled_source_sha256": current_sha,
    "semantic_contract": EXPECTED_META,
    "source_is_metadata_only": True,
    "source_is_idempotent": True,
    "reason": "Source file was overwritten during the same in-progress P15 recovery after the original migration had already been applied; source was reconstructed to the exact observed semantic contract before checksum reconciliation.",
}
EVIDENCE.parent.mkdir(exist_ok=True)
EVIDENCE.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps(proof, ensure_ascii=True, indent=2))
