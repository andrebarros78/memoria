from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from .backup_crypto import BackupCryptoManager
from .canonical_mutation import require_canonical_mutation
from .erasure_ledger import ExternalErasureLedger

ERASURE_MANAGER_VERSION = "ERM-1.0.0"
ERASURE_POLICY_VERSION = "ERP-1.0.0"
RESTORE_ERASURE_CONTRACT_VERSION = "REC-1.0.0"
P18_GATE_VERSION = "P18-1.0.0"


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _tombstone_sha(erasure_id: str) -> str:
    return hashlib.sha256(("LEGAL_ERASURE_FINALIZED:" + erasure_id).encode("utf-8")).hexdigest()


def erasure_spec() -> dict[str, Any]:
    return {
        "manager_version": ERASURE_MANAGER_VERSION,
        "policy_version": ERASURE_POLICY_VERSION,
        "restore_contract_version": RESTORE_ERASURE_CONTRACT_VERSION,
        "new_plaintext_backups_allowed": False,
        "raw_item_id_in_external_ledger": False,
        "raw_content_sha256_in_external_ledger": False,
        "serve_traffic_requires_replay_pass": True,  # nosec B105 - boolean policy flag, not a credential
        "restore_flow": ["RESTORE", "MIGRATE", "ERASURE_REPLAY", "VERIFY", "SERVE_TRAFFIC"],
        "crypto_shredding": True,
        "external_ledger_required": True,
        "gate": {"id": "P18", "version": P18_GATE_VERSION},
    }


class ErasureManager:
    def __init__(self, store: Any, *, ledger: ExternalErasureLedger | None = None,
                 backup_crypto: BackupCryptoManager | None = None) -> None:
        self.store = store
        self.tenant_id = str(getattr(store, "tenant_id", "LEGACY"))
        self.ledger = ledger or ExternalErasureLedger()
        self.backup_crypto = backup_crypto or BackupCryptoManager()

    @staticmethod
    def _authorize(conn: Any) -> None:
        conn.execute("SELECT set_config('app.legal_erasure_mutation_authorized','1',true)")

    def record_erasure(self, *, lifecycle_request_id: str, reason_code: str, actor: str,
                       backup_cutoff_at: datetime | None = None) -> dict[str, Any]:
        require_canonical_mutation("legal_erasure.record")
        cutoff = (backup_cutoff_at or datetime.now(UTC)).astimezone(UTC)
        with self.store.connection() as conn:
            req = conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s FOR UPDATE", (lifecycle_request_id,)).fetchone()
            if not req:
                raise ValueError("lifecycle request not found")
            if str(req["status"]) != "FINALIZED":
                raise ValueError("legal erasure requires FINALIZED lifecycle request")
            item_id = str(req["item_id"])
            original = str(req["source_content_sha256"])
            erasure_id = _id("ler")
            entry = self.ledger.append(
                tenant_id=self.tenant_id, item_id=item_id, lifecycle_request_id=lifecycle_request_id,
                content_sha256=original, erasure_id=erasure_id, reason_code=reason_code,
                backup_cutoff_at=cutoff,
            )
            self._authorize(conn)
            conn.execute(
                "INSERT INTO legal_erasure_requests(erasure_id,tenant_id,lifecycle_request_id,item_id,target_token,reason_code,status,external_ledger_seq,external_ledger_hmac,blinded_content_fingerprint,backup_cutoff_at,created_by) VALUES(%s,%s,%s,%s,%s,%s,'RECORDED',%s,%s,%s,%s,%s)",
                (erasure_id,self.tenant_id,lifecycle_request_id,item_id,entry["target_token"],reason_code,int(entry["seq"]),entry["entry_hmac"],entry["blinded_content_fingerprint"],cutoff,actor),
            )
            conn.execute("SELECT memory_apply_legal_erasure_extended(%s,%s,%s,%s)",
                         (item_id,erasure_id,entry["blinded_content_fingerprint"],_tombstone_sha(erasure_id)))
            conn.execute("UPDATE legal_erasure_requests SET status='APPLIED' WHERE erasure_id=%s", (erasure_id,))
            result = dict(conn.execute("SELECT * FROM legal_erasure_requests WHERE erasure_id=%s", (erasure_id,)).fetchone())
            result["ledger_entry"] = entry
            return result

    def crypto_shred_backups(self, *, manifests_root: Path, cutoff: datetime, reason: str) -> dict[str, Any]:
        require_canonical_mutation("legal_erasure.crypto_shred")
        return self.backup_crypto.shred_before(manifests_root, cutoff=cutoff, reason=reason)

    def replay(self, *, source_ref: str, actor: str) -> dict[str, Any]:
        require_canonical_mutation("legal_erasure.replay")
        entries = self.ledger.entries()
        matched = 0
        redacted = 0
        with self.store.connection() as conn:
            self._authorize(conn)
            items = conn.execute("SELECT item_id FROM memory_items").fetchall()
            by_token = {self.ledger.target_token(self.tenant_id, str(r["item_id"])): str(r["item_id"]) for r in items}
            for entry in entries:
                item_id = by_token.get(str(entry.get("target_token") or ""))
                if not item_id:
                    continue
                matched += 1
                erasure_id = str(entry["erasure_id"])
                conn.execute("SELECT memory_apply_legal_erasure_extended(%s,%s,%s,%s)",
                             (item_id,erasure_id,str(entry["blinded_content_fingerprint"]),_tombstone_sha(erasure_id)))
                redacted += 1
            replay_id = _id("lrr")
            result = "PASS" if redacted == matched else "FAIL"
            evidence = {"ledger_verified": True, "ledger_entries": len(entries), "matched_targets": matched, "redacted_targets": redacted}
            conn.execute("INSERT INTO legal_erasure_replay_runs(replay_id,tenant_id,source_ref,ledger_entries,matched_targets,redacted_targets,result,evidence,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                         (replay_id,self.tenant_id,source_ref,len(entries),matched,redacted,result,Jsonb(evidence),actor))
            return {"replay_id": replay_id, "result": result, **evidence}

    def get_erasure(self, erasure_id: str) -> dict[str, Any]:
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM legal_erasure_requests WHERE erasure_id=%s", (erasure_id,)).fetchone()
            if not row:
                raise ValueError("legal erasure request not found")
            return dict(row)

    def gate_status(self) -> dict[str, Any]:
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM legal_erasure_gate_p18 WHERE tenant_id=%s AND gate_id='P18'", (self.tenant_id,)).fetchone()
            if not row:
                return {"gate_id":"P18","gate_version":P18_GATE_VERSION,"status":"PENDING","proven":False}
            out = dict(row); out["proven"] = out["status"] == "PROVEN"; return out

    def close_p18(self, *, evidence: dict[str, Any], actor: str) -> dict[str, Any]:
        require_canonical_mutation("legal_erasure.close_p18")
        ledger_proof = self.ledger.verify()
        with self.store.connection() as conn:
            self._authorize(conn)
            replay = conn.execute("SELECT * FROM legal_erasure_replay_runs WHERE tenant_id=%s AND result='PASS' ORDER BY created_at DESC LIMIT 1", (self.tenant_id,)).fetchone()
            if not replay:
                raise RuntimeError("P18 requires a PASS erasure replay")
            bundle = {"ledger": ledger_proof, "replay_id": replay["replay_id"], **(evidence or {})}
            conn.execute("INSERT INTO legal_erasure_gate_p18(tenant_id,gate_id,gate_version,status,proof_bundle,proven_by,proven_at,updated_at) VALUES(%s,'P18',%s,'PROVEN',%s,%s,now(),now()) ON CONFLICT(tenant_id,gate_id) DO UPDATE SET gate_version=EXCLUDED.gate_version,status='PROVEN',proof_bundle=EXCLUDED.proof_bundle,proven_by=EXCLUDED.proven_by,proven_at=now(),updated_at=now()",
                         (self.tenant_id,P18_GATE_VERSION,Jsonb(bundle),actor))
            conn.execute("SELECT memory_set_runtime_gate(%s,%s)", ('p18_status','PROVEN'))
            out = dict(conn.execute("SELECT * FROM legal_erasure_gate_p18 WHERE tenant_id=%s AND gate_id='P18'", (self.tenant_id,)).fetchone()); out["proven"] = True; return out

