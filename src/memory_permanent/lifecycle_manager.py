from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from .canonical_mutation import require_canonical_mutation

LIFECYCLE_MANAGER_VERSION = "LCM-1.0.0"
LIFECYCLE_POLICY_VERSION = "LCP-1.0.0"
RECOVERY_CONTRACT_VERSION = "LRC-1.0.0"
GATE_M12_VERSION = "M12-1.0.0"
MAX_RECOVERY_WINDOW_SECONDS = 604800


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def validate_recovery_window(seconds: int) -> int:
    value = int(seconds)
    if value < 0 or value > MAX_RECOVERY_WINDOW_SECONDS:
        raise ValueError("recovery_window_seconds must be between 0 and 604800")
    return value


def lifecycle_spec(*, gate_status: str = "PENDING") -> dict[str, Any]:
    status = str(gate_status or "PENDING").upper()
    proven = status == "PROVEN"
    return {
        "manager_version": LIFECYCLE_MANAGER_VERSION,
        "policy_version": LIFECYCLE_POLICY_VERSION,
        "recovery_contract_version": RECOVERY_CONTRACT_VERSION,
        "workflow": ["DELETE_ELIGIBLE", "REQUESTED", "QUARANTINED", "APPROVED", "PURGED", "RECOVERED_OR_FINALIZED"],
        "separation_of_duties": True,
        "direct_purge_enabled": False,
        "gate": {"id": "M12", "version": GATE_M12_VERSION, "status": status, "proven": proven},
        "p0_ui_b": {"activation_allowed": proven, "direct_purge_route_stays_disabled": True},
    }


class LifecycleManager:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.tenant_id = str(getattr(store, "tenant_id", "LEGACY"))

    @staticmethod
    def _authorize(conn: Any) -> None:
        conn.execute("SELECT set_config('app.lifecycle_mutation_authorized','1',true)")

    def _event(self, conn: Any, *, event_type: str, actor: str, request_id: str | None = None,
               item_id: str | None = None, payload: dict[str, Any] | None = None) -> str:
        require_canonical_mutation("lifecycle.event")
        event_id = _id("lce")
        conn.execute(
            "INSERT INTO lifecycle_events(event_id,tenant_id,request_id,item_id,event_type,payload,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (event_id, self.tenant_id, request_id, item_id, event_type, Jsonb(payload or {}), actor),
        )
        return event_id

    def create_hold(self, *, item_id: str, hold_type: str, reason: str, actor: str) -> dict[str, Any]:
        require_canonical_mutation("lifecycle.create_hold")
        hold_id = _id("hold")
        with self.store.connection() as conn:
            if not conn.execute("SELECT 1 FROM memory_items WHERE item_id=%s", (item_id,)).fetchone():
                raise ValueError("memory not found")
            conn.execute(
                "INSERT INTO retention_holds(hold_id,item_id,hold_type,reason,created_by,status) VALUES(%s,%s,%s,%s,%s,'ACTIVE')",
                (hold_id, item_id, str(hold_type), str(reason), actor),
            )
            return dict(conn.execute("SELECT * FROM retention_holds WHERE hold_id=%s", (hold_id,)).fetchone())

    def release_hold(self, *, hold_id: str, actor: str) -> dict[str, Any]:
        require_canonical_mutation("lifecycle.release_hold")
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM retention_holds WHERE hold_id=%s FOR UPDATE", (hold_id,)).fetchone()
            if not row:
                raise ValueError("hold not found")
            conn.execute("UPDATE retention_holds SET status='RELEASED',released_at=now() WHERE hold_id=%s", (hold_id,))
            result = dict(conn.execute("SELECT * FROM retention_holds WHERE hold_id=%s", (hold_id,)).fetchone())
            result["released_by"] = actor
            return result

    def request_purge(self, *, item_id: str, reason: str, recovery_window_seconds: int,
                      evidence: dict[str, Any], actor: str) -> dict[str, Any]:
        require_canonical_mutation("lifecycle.request_purge")
        window = validate_recovery_window(recovery_window_seconds)
        request_id = _id("lcr")
        with self.store.connection() as conn:
            self._authorize(conn)
            item = conn.execute("SELECT * FROM memory_items WHERE item_id=%s FOR UPDATE", (item_id,)).fetchone()
            if not item:
                raise ValueError("memory not found")
            op = conn.execute("SELECT * FROM memory_operator_state WHERE item_id=%s", (item_id,)).fetchone()
            if not op or str(op["lifecycle_state"]) != "DELETE_ELIGIBLE":
                raise ValueError("memory must be DELETE_ELIGIBLE before lifecycle request")
            if conn.execute("SELECT 1 FROM retention_holds WHERE item_id=%s AND status='ACTIVE' LIMIT 1", (item_id,)).fetchone():
                raise ValueError("active retention hold blocks purge request")
            ver = conn.execute("SELECT version_no,content_sha256 FROM memory_versions WHERE item_id=%s ORDER BY version_no DESC LIMIT 1", (item_id,)).fetchone()
            conn.execute(
                "INSERT INTO lifecycle_requests(request_id,tenant_id,item_id,policy_version,requested_by,reason,status,source_version_no,source_content_sha256,recovery_window_seconds,request_evidence) VALUES(%s,%s,%s,%s,%s,%s,'REQUESTED',%s,%s,%s,%s)",
                (request_id,self.tenant_id,item_id,LIFECYCLE_POLICY_VERSION,actor,reason,int(ver["version_no"]),str(ver["content_sha256"]),window,Jsonb(evidence or {})),
            )
            self._event(conn,event_type="LIFECYCLE_REQUESTED",actor=actor,request_id=request_id,item_id=item_id,payload={"recovery_window_seconds":window})
            return dict(conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s", (request_id,)).fetchone())

    def get_request(self, request_id: str) -> dict[str, Any]:
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s", (request_id,)).fetchone()
            if not row:
                raise ValueError("lifecycle request not found")
            return dict(row)

    def quarantine(self, *, request_id: str, evidence: dict[str, Any], actor: str) -> dict[str, Any]:
        require_canonical_mutation("lifecycle.quarantine")
        with self.store.connection() as conn:
            self._authorize(conn)
            req = conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s FOR UPDATE", (request_id,)).fetchone()
            if not req or req["status"] != "REQUESTED":
                raise ValueError("request must be REQUESTED")
            item_id = str(req["item_id"])
            item = dict(conn.execute("SELECT memory_key,content_json,content_text,provenance,confidence,source,source_version,tags,content_sha256,validation_status,governor_eligible FROM memory_items WHERE item_id=%s",(item_id,)).fetchone())
            op = dict(conn.execute("SELECT operator_class,lifecycle_state,hold_type,changed_by FROM memory_operator_state WHERE item_id=%s",(item_id,)).fetchone())
            versions=[dict(r) for r in conn.execute("SELECT version_id,version_no,content_json,content_text,provenance,confidence,source,source_version,tags,content_sha256,request_sha256 FROM memory_versions WHERE item_id=%s ORDER BY version_no",(item_id,)).fetchall()]
            payload={"item":item,"operator_state":op,"versions":versions,"request_evidence":evidence or {}}
            snapshot_id=_id("lcs")
            conn.execute("INSERT INTO lifecycle_recovery_snapshots(snapshot_id,tenant_id,request_id,item_id,payload_json,payload_sha256,status) VALUES(%s,%s,%s,%s,%s,%s,'ACTIVE')",
                         (snapshot_id,self.tenant_id,request_id,item_id,Jsonb(payload),_sha(payload)))
            conn.execute("UPDATE lifecycle_requests SET status='QUARANTINED',quarantined_at=now() WHERE request_id=%s",(request_id,))
            self._event(conn,event_type="LIFECYCLE_QUARANTINED",actor=actor,request_id=request_id,item_id=item_id,payload={"snapshot_id":snapshot_id})
            out=dict(conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s",(request_id,)).fetchone()); out["snapshot_id"]=snapshot_id; return out

    def approve(self, *, request_id: str, evidence: dict[str, Any], actor: str) -> dict[str, Any]:
        require_canonical_mutation("lifecycle.approve")
        with self.store.connection() as conn:
            self._authorize(conn)
            req=conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s FOR UPDATE",(request_id,)).fetchone()
            if not req or req["status"] != "QUARANTINED": raise ValueError("request must be QUARANTINED")
            if str(req["requested_by"]) == str(actor): raise ValueError("requester cannot approve own purge")
            if conn.execute("SELECT 1 FROM retention_holds WHERE item_id=%s AND status='ACTIVE' LIMIT 1",(req["item_id"],)).fetchone(): raise ValueError("active hold blocks approval")
            conn.execute("UPDATE lifecycle_requests SET status='APPROVED',approved_by=%s,approved_at=now(),approval_evidence=%s WHERE request_id=%s",(actor,Jsonb(evidence or {}),request_id))
            self._event(conn,event_type="LIFECYCLE_APPROVED",actor=actor,request_id=request_id,item_id=str(req["item_id"]),payload=evidence or {})
            return dict(conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s",(request_id,)).fetchone())

    def purge(self, *, request_id: str, evidence: dict[str, Any], actor: str) -> dict[str, Any]:
        require_canonical_mutation("lifecycle.purge")
        with self.store.connection() as conn:
            self._authorize(conn)
            conn.execute("SELECT set_config('app.lifecycle_irreversible_mutation','1',true)")
            req=conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s FOR UPDATE",(request_id,)).fetchone()
            if not req or req["status"] != "APPROVED": raise ValueError("request must be APPROVED")
            item_id=str(req["item_id"])
            if conn.execute("SELECT 1 FROM retention_holds WHERE item_id=%s AND status='ACTIVE' LIMIT 1",(item_id,)).fetchone(): raise ValueError("active hold blocks purge")
            marker={"_lifecycle":"PURGED","request_id":request_id}; marker_sha=_sha(marker)
            conn.execute("UPDATE memory_items SET content_json=%s,content_text='[LIFECYCLE_PURGED]',provenance=%s,confidence=0,source='lifecycle',source_version=%s,tags=ARRAY['LIFECYCLE_PURGED'],content_sha256=%s,validation_status='UNVALIDATED',governor_eligible=false WHERE item_id=%s",
                         (Jsonb(marker),Jsonb(marker),LIFECYCLE_MANAGER_VERSION,marker_sha,item_id))
            conn.execute("UPDATE memory_versions SET content_json=%s,content_text='[LIFECYCLE_PURGED]',provenance=%s,confidence=0,source='lifecycle',source_version=%s,tags=ARRAY['LIFECYCLE_PURGED'],content_sha256=%s WHERE item_id=%s",
                         (Jsonb(marker),Jsonb(marker),LIFECYCLE_MANAGER_VERSION,marker_sha,item_id))
            conn.execute("DELETE FROM memory_embeddings WHERE item_id=%s",(item_id,))
            conn.execute("UPDATE memory_operator_state SET lifecycle_state='PURGED',changed_by=%s,changed_at=now() WHERE item_id=%s",(actor,item_id))
            recover_until=datetime.now(UTC)+timedelta(seconds=int(req["recovery_window_seconds"]))
            conn.execute("UPDATE lifecycle_requests SET status='PURGED',purged_at=now(),recover_until=%s,purge_evidence=%s WHERE request_id=%s",(recover_until,Jsonb(evidence or {}),request_id))
            tombstone_id=_id("lct")
            conn.execute("INSERT INTO lifecycle_tombstones(tombstone_id,tenant_id,request_id,item_id,state,original_content_sha256,metadata) VALUES(%s,%s,%s,%s,'PURGED',%s,%s)",
                         (tombstone_id,self.tenant_id,request_id,item_id,str(req["source_content_sha256"]),Jsonb({"policy":LIFECYCLE_POLICY_VERSION})))
            self._event(conn,event_type="LIFECYCLE_PURGED",actor=actor,request_id=request_id,item_id=item_id,payload={"tombstone_id":tombstone_id,"recover_until":recover_until.isoformat()})
            out=dict(conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s",(request_id,)).fetchone()); out["tombstone_id"]=tombstone_id; return out

    def recover(self, *, request_id: str, evidence: dict[str, Any], actor: str) -> dict[str, Any]:
        require_canonical_mutation("lifecycle.recover")
        with self.store.connection() as conn:
            self._authorize(conn); conn.execute("SELECT set_config('app.lifecycle_irreversible_mutation','1',true)")
            req=conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s FOR UPDATE",(request_id,)).fetchone()
            if not req or req["status"] != "PURGED": raise ValueError("request must be PURGED")
            if req["recover_until"] is not None and datetime.now(UTC) > req["recover_until"]: raise ValueError("recovery window expired")
            snap=conn.execute("SELECT * FROM lifecycle_recovery_snapshots WHERE request_id=%s FOR UPDATE",(request_id,)).fetchone()
            if not snap or snap["status"] != "ACTIVE": raise ValueError("active recovery snapshot missing")
            payload=snap["payload_json"]
            if _sha(payload) != str(snap["payload_sha256"]): raise RuntimeError("recovery snapshot hash mismatch")
            item=payload["item"]; item_id=str(req["item_id"])
            conn.execute("UPDATE memory_items SET memory_key=%s,content_json=%s,content_text=%s,provenance=%s,confidence=%s,source=%s,source_version=%s,tags=%s,content_sha256=%s,validation_status=%s,governor_eligible=%s WHERE item_id=%s",
                         (item["memory_key"],Jsonb(item["content_json"]),item["content_text"],Jsonb(item["provenance"]),item["confidence"],item["source"],item["source_version"],item["tags"],item["content_sha256"],item["validation_status"],item["governor_eligible"],item_id))
            for v in payload["versions"]:
                conn.execute("UPDATE memory_versions SET content_json=%s,content_text=%s,provenance=%s,confidence=%s,source=%s,source_version=%s,tags=%s,content_sha256=%s,request_sha256=%s WHERE version_id=%s",
                             (Jsonb(v["content_json"]),v["content_text"],Jsonb(v["provenance"]),v["confidence"],v["source"],v["source_version"],v["tags"],v["content_sha256"],v["request_sha256"],v["version_id"]))
            op=payload["operator_state"]
            conn.execute("UPDATE memory_operator_state SET operator_class=%s,lifecycle_state='DELETE_ELIGIBLE',hold_type=%s,changed_by=%s,changed_at=now() WHERE item_id=%s",(op["operator_class"],op["hold_type"],actor,item_id))
            conn.execute("UPDATE lifecycle_recovery_snapshots SET status='CONSUMED' WHERE request_id=%s",(request_id,))
            conn.execute("UPDATE lifecycle_tombstones SET state='RECOVERED',updated_at=now() WHERE request_id=%s",(request_id,))
            conn.execute("UPDATE lifecycle_requests SET status='RECOVERED',recovered_at=now() WHERE request_id=%s",(request_id,))
            restored=conn.execute("SELECT content_sha256 FROM memory_items WHERE item_id=%s",(item_id,)).fetchone(); ok=str(restored["content_sha256"])==str(req["source_content_sha256"])
            proof_id=_id("lcp")
            conn.execute("INSERT INTO lifecycle_recovery_proofs(proof_id,tenant_id,request_id,proof_type,result,evidence,created_by) VALUES(%s,%s,%s,'ROUNDTRIP_RECOVERY',%s,%s,%s)",
                         (proof_id,self.tenant_id,request_id,'PASS' if ok else 'FAIL',Jsonb({"expected_sha":str(req["source_content_sha256"]),"restored_sha":str(restored["content_sha256"]),**(evidence or {})}),actor))
            self._event(conn,event_type="LIFECYCLE_RECOVERED",actor=actor,request_id=request_id,item_id=item_id,payload={"proof_id":proof_id,"result":"PASS" if ok else "FAIL"})
            if not ok: raise RuntimeError("roundtrip recovery proof failed")
            out=dict(conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s",(request_id,)).fetchone()); out["roundtrip_proof_id"]=proof_id; return out

    def finalize(self, *, request_id: str, evidence: dict[str, Any], actor: str) -> dict[str, Any]:
        require_canonical_mutation("lifecycle.finalize")
        with self.store.connection() as conn:
            self._authorize(conn)
            req=conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s FOR UPDATE",(request_id,)).fetchone()
            if not req or req["status"] != "PURGED": raise ValueError("request must be PURGED")
            if req["recover_until"] is not None and datetime.now(UTC) < req["recover_until"]: raise ValueError("recovery window not expired")
            item_id=str(req["item_id"])
            if conn.execute("SELECT 1 FROM retention_holds WHERE item_id=%s AND status='ACTIVE' LIMIT 1",(item_id,)).fetchone(): raise ValueError("active hold blocks finalization")
            final_hash=_sha({"_lifecycle":"FINALIZED","request_id":request_id})
            conn.execute("SELECT memory_lifecycle_finalize_payload(%s,%s,%s)",(request_id,item_id,final_hash))
            snap=conn.execute("SELECT status,payload_json FROM lifecycle_recovery_snapshots WHERE request_id=%s",(request_id,)).fetchone()
            counts=conn.execute("SELECT count(*) AS n,count(*) FILTER(WHERE content_text='[LIFECYCLE_FINALIZED]' AND content_sha256=%s) AS redacted FROM memory_versions WHERE item_id=%s",(final_hash,item_id)).fetchone()
            ok=bool(snap and snap["status"]=='DESTROYED' and snap["payload_json"]=={} and int(counts["n"])==int(counts["redacted"]))
            proof_id=_id("lcp")
            conn.execute("INSERT INTO lifecycle_recovery_proofs(proof_id,tenant_id,request_id,proof_type,result,evidence,created_by) VALUES(%s,%s,%s,'IRREVERSIBILITY',%s,%s,%s)",
                         (proof_id,self.tenant_id,request_id,'PASS' if ok else 'FAIL',Jsonb({"snapshot_status":snap["status"] if snap else None,"versions":int(counts["n"]),**(evidence or {})}),actor))
            self._event(conn,event_type="LIFECYCLE_FINALIZED",actor=actor,request_id=request_id,item_id=item_id,payload={"proof_id":proof_id,"result":"PASS" if ok else "FAIL"})
            if not ok: raise RuntimeError("irreversibility proof failed")
            out=dict(conn.execute("SELECT * FROM lifecycle_requests WHERE request_id=%s",(request_id,)).fetchone()); out.update({"snapshot_status":"DESTROYED","irreversibility_proof_id":proof_id}); return out

    def gate_status(self) -> dict[str, Any]:
        with self.store.connection() as conn:
            row=conn.execute("SELECT * FROM lifecycle_gate_m12 WHERE gate_id='M12' ORDER BY proven_at DESC NULLS LAST LIMIT 1").fetchone()
            if not row: return {"gate_id":"M12","gate_version":GATE_M12_VERSION,"status":"PENDING","proven":False}
            out=dict(row); out["proven"]=out["status"]=="PROVEN"; return out

    def close_m12(self, *, evidence: dict[str, Any], actor: str) -> dict[str, Any]:
        require_canonical_mutation("lifecycle.close_m12")
        audit=self.store.verify_audit_chain()
        if not audit.get("valid", audit.get("ok", False)): raise RuntimeError("audit chain is not valid")
        with self.store.connection() as conn:
            self._authorize(conn)
            policy=conn.execute("SELECT policy_version,status FROM lifecycle_policies WHERE policy_version=%s",(LIFECYCLE_POLICY_VERSION,)).fetchone()
            rt=conn.execute("SELECT proof_id,request_id FROM lifecycle_recovery_proofs WHERE proof_type='ROUNDTRIP_RECOVERY' AND result='PASS' ORDER BY created_at DESC LIMIT 1").fetchone()
            irr=conn.execute("SELECT proof_id,request_id FROM lifecycle_recovery_proofs WHERE proof_type='IRREVERSIBILITY' AND result='PASS' ORDER BY created_at DESC LIMIT 1").fetchone()
            sep=conn.execute("SELECT request_id,requested_by,approved_by FROM lifecycle_requests WHERE approved_by IS NOT NULL AND approved_by<>requested_by ORDER BY approved_at DESC LIMIT 1").fetchone()
            direct=conn.execute("SELECT value FROM schema_meta WHERE key='lifecycle_direct_purge_enabled'").fetchone()
            checks={"policy_active":bool(policy and policy["status"]=='ACTIVE'),"roundtrip":bool(rt),"irreversibility":bool(irr),"separation":bool(sep),"direct_purge_disabled":bool(direct and direct["value"]=='false'),"audit":True}
            if not all(checks.values()): raise RuntimeError("M12 proof prerequisites are incomplete: "+_canon(checks))
            bundle={"checks":checks,"roundtrip_proof_id":rt["proof_id"],"irreversibility_proof_id":irr["proof_id"],"separation_request_id":sep["request_id"],**(evidence or {})}
            conn.execute("INSERT INTO lifecycle_gate_m12(tenant_id,gate_id,gate_version,status,policy_version,proof_bundle,proven_by,proven_at,updated_at) VALUES(%s,'M12',%s,'PROVEN',%s,%s,%s,now(),now()) ON CONFLICT(tenant_id,gate_id) DO UPDATE SET gate_version=EXCLUDED.gate_version,status='PROVEN',policy_version=EXCLUDED.policy_version,proof_bundle=EXCLUDED.proof_bundle,proven_by=EXCLUDED.proven_by,proven_at=now(),updated_at=now()",
                         (self.tenant_id,GATE_M12_VERSION,LIFECYCLE_POLICY_VERSION,Jsonb(bundle),actor))
            conn.execute("SELECT memory_set_runtime_gate(%s,%s)", ('gate_m12_status','PROVEN'))
            self._event(conn,event_type="GATE_M12_PROVEN",actor=actor,payload=bundle)
            out=dict(conn.execute("SELECT * FROM lifecycle_gate_m12 WHERE tenant_id=%s AND gate_id='M12'",(self.tenant_id,)).fetchone()); out["proven"]=True; return out
