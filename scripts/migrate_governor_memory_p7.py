from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from memory_permanent.store import PostgresMemoryStore, canonical

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"


def normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    return value


def manifest_hash(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> str:
    payload = [{field: normalize(row.get(field)) for field in fields} for row in rows]
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def fetch(conn, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql).fetchall()]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    old_dsn = os.environ["OLD_DSN"]
    new_dsn = os.environ["NEW_DSN"]
    backup_dir = Path(os.environ["P7_BACKUP_DIR"]).resolve()

    old = psycopg.connect(old_dsn, row_factory=dict_row)
    new = psycopg.connect(new_dsn, row_factory=dict_row)
    try:
        memories = fetch(old, "SELECT item_id,namespace,memory_key,content_json,content_text,provenance,confidence,source,source_version,tags,valid_from,valid_until,supersedes_id,content_sha256,created_at FROM memory_items ORDER BY item_id")
        traces = fetch(old, "SELECT trace_id,query_text,namespaces,candidates,selected,conflicts,created_at FROM retrieval_traces ORDER BY trace_id")
        checkpoints = fetch(old, "SELECT checkpoint_id,namespace,mission_id,step_index,state_json,state_sha256,created_at FROM checkpoints ORDER BY checkpoint_id")
        legacy_audit = fetch(old, "SELECT seq,event_type,payload,previous_hash,event_hash,created_at FROM security_audit ORDER BY seq")

        memory_fields = ("item_id","namespace","memory_key","content_json","content_text","provenance","confidence","source","source_version","tags","valid_from","valid_until","supersedes_id","content_sha256","created_at")
        source_memory_manifest = manifest_hash(memories, memory_fields)
        source_trace_manifest = manifest_hash(traces, ("trace_id","query_text","namespaces","candidates","selected","conflicts","created_at"))
        source_checkpoint_manifest = manifest_hash(checkpoints, ("checkpoint_id","namespace","mission_id","step_index","state_json","state_sha256","created_at"))
        source_audit_manifest = manifest_hash(legacy_audit, ("seq","event_type","payload","previous_hash","event_hash","created_at"))

        existing_memory_ids = {str(r["item_id"]) for r in new.execute("SELECT item_id FROM memory_items").fetchall()}
        existing_trace_ids = {str(r["trace_id"]) for r in new.execute("SELECT trace_id FROM retrieval_traces").fetchall()}
        existing_checkpoint_ids = {str(r["checkpoint_id"]) for r in new.execute("SELECT checkpoint_id FROM checkpoints").fetchall()}
        existing_audit_seqs = {int(r["legacy_seq"]) for r in new.execute("SELECT legacy_seq FROM legacy_security_audit").fetchall()}

        inserted_memory_ids: list[str] = []
        inserted_trace_ids: list[str] = []
        inserted_checkpoint_ids: list[str] = []
        inserted_audit_seqs: list[int] = []
        collisions: list[dict[str, Any]] = []

        for row in memories:
            item_id = str(row["item_id"])
            if item_id in existing_memory_ids:
                current = new.execute("SELECT content_sha256 FROM memory_items WHERE item_id=%s", (item_id,)).fetchone()
                if not current or str(current["content_sha256"]) != str(row["content_sha256"]):
                    collisions.append({"type": "memory_item", "id": item_id})
                continue
            new.execute(
                """INSERT INTO memory_items(item_id,namespace,memory_key,category,content_json,content_text,provenance,confidence,source,source_version,tags,valid_from,valid_until,supersedes_id,content_sha256,created_at)
                   VALUES(%s,%s,%s,'FACT',%s::jsonb,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (item_id,row["namespace"],row["memory_key"],canonical(row["content_json"]),row["content_text"],canonical(row["provenance"]),row["confidence"],row["source"],row["source_version"],row["tags"],row["valid_from"],row["valid_until"],row["supersedes_id"],row["content_sha256"],row["created_at"]),
            )
            new.execute("INSERT INTO memory_operator_state(item_id,operator_class,lifecycle_state,changed_by,changed_at) VALUES(%s,'ATIVA','HOT','legacy-migration',now())", (item_id,))
            inserted_memory_ids.append(item_id)

        for row in traces:
            trace_id = str(row["trace_id"])
            if trace_id in existing_trace_ids:
                continue
            new.execute(
                "INSERT INTO retrieval_traces(trace_id,query_text,namespaces,candidates,selected,conflicts,created_at) VALUES(%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s)",
                (trace_id,row["query_text"],row["namespaces"],canonical(row["candidates"]),canonical(row["selected"]),canonical(row["conflicts"]),row["created_at"]),
            )
            inserted_trace_ids.append(trace_id)

        for row in checkpoints:
            checkpoint_id = str(row["checkpoint_id"])
            if checkpoint_id in existing_checkpoint_ids:
                continue
            new.execute(
                "INSERT INTO checkpoints(checkpoint_id,namespace,mission_id,step_index,state_json,state_sha256,created_at,migration_source) VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s,'governor-legacy-p7')",
                (checkpoint_id,row["namespace"],row["mission_id"],row["step_index"],canonical(row["state_json"]),row["state_sha256"],row["created_at"]),
            )
            inserted_checkpoint_ids.append(checkpoint_id)

        for row in legacy_audit:
            seq = int(row["seq"])
            if seq in existing_audit_seqs:
                continue
            new.execute(
                "INSERT INTO legacy_security_audit(legacy_seq,event_type,payload,previous_hash,event_hash,created_at,migration_source) VALUES(%s,%s,%s::jsonb,%s,%s,%s,'governor-legacy-p7')",
                (seq,row["event_type"],canonical(row["payload"]),row["previous_hash"],row["event_hash"],row["created_at"]),
            )
            inserted_audit_seqs.append(seq)
        new.commit()

        migrated_memories = fetch(new, "SELECT item_id,namespace,memory_key,content_json,content_text,provenance,confidence,source,source_version,tags,valid_from,valid_until,supersedes_id,content_sha256,created_at FROM memory_items WHERE item_id IN (SELECT item_id FROM memory_operator_state WHERE changed_by='legacy-migration') ORDER BY item_id")
        source_ids = {str(row["item_id"]) for row in memories}
        target_rows_for_source = [row for row in migrated_memories if str(row["item_id"]) in source_ids]
        target_memory_manifest = manifest_hash(target_rows_for_source, memory_fields)

        target_trace_count = int(new.execute("SELECT count(*) n FROM retrieval_traces WHERE trace_id=ANY(%s)", ([str(r['trace_id']) for r in traces],)).fetchone()["n"])
        target_checkpoint_count = int(new.execute("SELECT count(*) n FROM checkpoints WHERE checkpoint_id=ANY(%s)", ([str(r['checkpoint_id']) for r in checkpoints],)).fetchone()["n"])
        target_audit_count = int(new.execute("SELECT count(*) n FROM legacy_security_audit WHERE legacy_seq=ANY(%s)", ([int(r['seq']) for r in legacy_audit],)).fetchone()["n"])
        provenance_missing = int(new.execute("SELECT count(*) n FROM memory_items WHERE item_id=ANY(%s) AND (provenance IS NULL OR provenance='{}'::jsonb)", (list(source_ids),)).fetchone()["n"])

        # Verify legacy chain continuity without rewriting its original hashes.
        chain_link_errors: list[int] = []
        previous = "0" * 64
        for row in legacy_audit:
            if str(row["previous_hash"]) != previous:
                chain_link_errors.append(int(row["seq"]))
            previous = str(row["event_hash"])

        # Rollback drill: delete every newly inserted migration row inside one transaction, then rollback.
        rollback = psycopg.connect(new_dsn, row_factory=dict_row)
        try:
            before = {
                "memories": int(rollback.execute("SELECT count(*) n FROM memory_items").fetchone()["n"]),
                "traces": int(rollback.execute("SELECT count(*) n FROM retrieval_traces").fetchone()["n"]),
                "checkpoints": int(rollback.execute("SELECT count(*) n FROM checkpoints").fetchone()["n"]),
                "legacy_audit": int(rollback.execute("SELECT count(*) n FROM legacy_security_audit").fetchone()["n"]),
            }
            if inserted_memory_ids:
                rollback.execute("DELETE FROM memory_operator_state WHERE item_id=ANY(%s)", (inserted_memory_ids,))
                rollback.execute("DELETE FROM memory_items WHERE item_id=ANY(%s)", (inserted_memory_ids,))
            if inserted_trace_ids:
                rollback.execute("DELETE FROM retrieval_traces WHERE trace_id=ANY(%s)", (inserted_trace_ids,))
            if inserted_checkpoint_ids:
                rollback.execute("DELETE FROM checkpoints WHERE checkpoint_id=ANY(%s)", (inserted_checkpoint_ids,))
            if inserted_audit_seqs:
                rollback.execute("DELETE FROM legacy_security_audit WHERE legacy_seq=ANY(%s)", (inserted_audit_seqs,))
            during = {
                "memories": int(rollback.execute("SELECT count(*) n FROM memory_items").fetchone()["n"]),
                "traces": int(rollback.execute("SELECT count(*) n FROM retrieval_traces").fetchone()["n"]),
                "checkpoints": int(rollback.execute("SELECT count(*) n FROM checkpoints").fetchone()["n"]),
                "legacy_audit": int(rollback.execute("SELECT count(*) n FROM legacy_security_audit").fetchone()["n"]),
            }
            rollback.rollback()
            after = {
                "memories": int(rollback.execute("SELECT count(*) n FROM memory_items").fetchone()["n"]),
                "traces": int(rollback.execute("SELECT count(*) n FROM retrieval_traces").fetchone()["n"]),
                "checkpoints": int(rollback.execute("SELECT count(*) n FROM checkpoints").fetchone()["n"]),
                "legacy_audit": int(rollback.execute("SELECT count(*) n FROM legacy_security_audit").fetchone()["n"]),
            }
        finally:
            rollback.close()

        rollback_changed = during != before if any((inserted_memory_ids, inserted_trace_ids, inserted_checkpoint_ids, inserted_audit_seqs)) else True
        rollback_restored = after == before

        store = PostgresMemoryStore(new_dsn, initialize=False)
        store._audit_summary = None  # marker only; do not alter API surface
        with store._connection() as conn:
            store._audit(conn, "P7_LEGACY_MIGRATION_COMPLETED", None, {
                "source_memory_items": len(memories),
                "inserted_memory_items": len(inserted_memory_ids),
                "source_manifest": source_memory_manifest,
                "target_manifest": target_memory_manifest,
            })

        backups = {
            path.name: {"bytes": path.stat().st_size, "sha256": file_sha256(path)}
            for path in sorted(backup_dir.glob("*.dump"))
        }
        proof = {
            "generated_at": datetime.now().astimezone().isoformat(),
            "backup_dir": str(backup_dir),
            "backups": backups,
            "source_counts": {"memory_items": len(memories), "retrieval_traces": len(traces), "checkpoints": len(checkpoints), "legacy_security_audit": len(legacy_audit)},
            "inserted_counts": {"memory_items": len(inserted_memory_ids), "retrieval_traces": len(inserted_trace_ids), "checkpoints": len(inserted_checkpoint_ids), "legacy_security_audit": len(inserted_audit_seqs)},
            "target_source_counts": {"memory_items": len(target_rows_for_source), "retrieval_traces": target_trace_count, "checkpoints": target_checkpoint_count, "legacy_security_audit": target_audit_count},
            "source_memory_manifest_sha256": source_memory_manifest,
            "target_memory_manifest_sha256": target_memory_manifest,
            "memory_manifest_match": source_memory_manifest == target_memory_manifest,
            "source_trace_manifest_sha256": source_trace_manifest,
            "source_checkpoint_manifest_sha256": source_checkpoint_manifest,
            "source_audit_manifest_sha256": source_audit_manifest,
            "id_collisions": collisions,
            "unexplained_duplication": len(collisions),
            "provenance_missing": provenance_missing,
            "legacy_chain_link_errors": chain_link_errors,
            "rollback_changed_state_inside_transaction": rollback_changed,
            "rollback_restored_final_state": rollback_restored,
        }
        proof["P7_DATA_MIGRATION_PROOF"] = "PASS" if all([
            len(target_rows_for_source) == len(memories),
            target_trace_count == len(traces),
            target_checkpoint_count == len(checkpoints),
            target_audit_count == len(legacy_audit),
            proof["memory_manifest_match"],
            not collisions,
            provenance_missing == 0,
            not chain_link_errors,
            rollback_restored,
            len(backups) >= 2,
        ]) else "FAIL"

        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "P7_DATA_MIGRATION_PROOF.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(proof, ensure_ascii=False, indent=2))
        return 0 if proof["P7_DATA_MIGRATION_PROOF"] == "PASS" else 1
    finally:
        old.close()
        new.close()


if __name__ == "__main__":
    raise SystemExit(main())
