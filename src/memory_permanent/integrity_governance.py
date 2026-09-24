from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from .canonical_mutation import require_canonical_mutation
from .integrity_anchor import CONTRACT, IntegrityAnchorManager

INTEGRITY_GOVERNANCE_CONTRACT = "M16-1.0.0"


def default_anchor_root() -> Path:
    configured = os.getenv("MEMORY_INTEGRITY_ANCHOR_ROOT", "").strip()
    if configured:
        return Path(configured)
    if os.name == "nt":
        return Path(os.getenv("ProgramData", r"C:\ProgramData")) / "MemoriaPermanente" / "integrity-anchors"
    return Path("/var/lib/memoria-permanente/integrity-anchors")


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


class IntegrityGovernance:
    """M16 persistence/audit boundary over independently stored signed anchors."""

    def __init__(self, store: Any, *, anchor_root: str | Path | None = None) -> None:
        self.store = store
        self.tenant_id = str(getattr(store, "tenant_id", "LEGACY"))
        self.anchor_root = Path(anchor_root) if anchor_root is not None else default_anchor_root()
        self.manager = IntegrityAnchorManager(anchor_root=self.anchor_root)

    def _event(
        self,
        conn: Any,
        *,
        actor: str,
        event_type: str,
        status: str,
        manifest_id: str | None,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        require_canonical_mutation("integrity.event")
        event_id = _id("iae")
        conn.execute(
            """INSERT INTO integrity_anchor_events(
                 event_id,tenant_id,manifest_id,event_type,status,detail_jsonb,created_by
               ) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            (event_id, self.tenant_id, manifest_id, event_type, status, Jsonb(detail), actor),
        )
        if hasattr(self.store, "_audit"):
            self.store._audit(
                conn,
                f"INTEGRITY_{event_type}",
                manifest_id,
                {"event_id": event_id, "status": status, "detail": detail},
            )
        return {"event_id": event_id, "event_type": event_type, "status": status}

    def _persist_manifest(self, conn: Any, manifest: dict[str, Any]) -> None:
        require_canonical_mutation("integrity.manifest")
        conn.execute(
            """INSERT INTO integrity_manifests(
                 manifest_id,tenant_id,scope_type,scope_id,range_start,range_end,root_hash,
                 previous_manifest_hash,manifest_hash,signature_algorithm,signature_key_version,
                 public_key_sha256,signature_b64,external_anchor_ref,verification_state,anchored_at,metadata_jsonb
               ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'VERIFIED',%s,%s)""",
            (
                manifest["manifest_id"],
                self.tenant_id,
                manifest["scope_type"],
                manifest["scope_id"],
                str(manifest["range_start"]) if manifest.get("range_start") is not None else None,
                str(manifest["range_end"]) if manifest.get("range_end") is not None else None,
                manifest["root_hash"],
                manifest.get("previous_manifest_hash"),
                manifest["manifest_hash"],
                manifest["signature_algorithm"],
                int(manifest["signature_key_version"]),
                manifest["public_key_sha256"],
                manifest["signature_b64"],
                manifest["external_anchor_ref"],
                manifest["created_at"],
                Jsonb(dict(manifest.get("metadata") or {})),
            ),
        )

    def status(self) -> dict[str, Any]:
        with self.store.connection() as conn:
            manifest = conn.execute(
                """SELECT manifest_id,scope_type,scope_id,root_hash,manifest_hash,signature_key_version,
                          external_anchor_ref,verification_state,anchored_at,created_at
                   FROM integrity_manifests ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
            counts = conn.execute(
                """SELECT count(*) AS events,
                          count(*) FILTER(WHERE event_type='VERIFY_FAIL') AS verify_fail,
                          count(*) FILTER(WHERE event_type='ANCHOR_DEGRADED') AS degraded
                   FROM integrity_anchor_events"""
            ).fetchone()
        return {
            "contract": INTEGRITY_GOVERNANCE_CONTRACT,
            "anchor_contract": CONTRACT,
            "anchor_root": str(self.anchor_root),
            "latest_manifest": {k: _iso(v) for k, v in dict(manifest).items()} if manifest else None,
            "events": int(counts["events"] or 0),
            "verify_failures": int(counts["verify_fail"] or 0),
            "degraded_events": int(counts["degraded"] or 0),
            "canonical_write_blocked_on_anchor_failure": False,
        }

    def create_audit_manifest(self, *, actor: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        require_canonical_mutation("integrity.create")
        audit = self.store.verify_audit_chain()
        valid = bool(audit.get("valid", audit.get("ok", False)))
        if not valid:
            raise RuntimeError("audit chain must be valid before anchoring")
        event_count = int(audit.get("events") or 0)
        root_hash = str(audit.get("head") or "")
        result = self.manager.try_anchor(
            root_hash=root_hash,
            scope_type="AUDIT_CHAIN",
            scope_id=self.tenant_id,
            range_start=1 if event_count else 0,
            range_end=event_count,
            metadata={"audit_chain": True, "events": event_count, **(metadata or {})},
        )
        if not result.get("anchored"):
            with self.store.connection() as conn:
                event = self._event(
                    conn,
                    actor=actor,
                    event_type="ANCHOR_DEGRADED",
                    status="DEGRADED",
                    manifest_id=None,
                    detail={k: v for k, v in result.items() if k != "manifest"},
                )
            return {"contract": INTEGRITY_GOVERNANCE_CONTRACT, **result, "event": event}
        manifest = dict(result["manifest"])
        verification = self.manager.verify_manifest(manifest["external_anchor_ref"])
        if not verification.get("valid"):
            raise RuntimeError("newly created integrity anchor failed immediate verification")
        with self.store.connection() as conn:
            self._persist_manifest(conn, manifest)
            event = self._event(
                conn,
                actor=actor,
                event_type="ANCHOR_CREATED",
                status="PASS",
                manifest_id=manifest["manifest_id"],
                detail={"manifest_hash": manifest["manifest_hash"], "root_hash": manifest["root_hash"]},
            )
        return {
            "contract": INTEGRITY_GOVERNANCE_CONTRACT,
            "state": "ANCHORED",
            "anchored": True,
            "canonical_write_blocked": False,
            "manifest": manifest,
            "verification": verification,
            "event": event,
        }

    def verify(self, *, manifest_id: str, actor: str) -> dict[str, Any]:
        require_canonical_mutation("integrity.verify")
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM integrity_manifests WHERE manifest_id=%s",
                (manifest_id,),
            ).fetchone()
            if not row:
                raise KeyError(manifest_id)
            previous = conn.execute(
                """SELECT manifest_hash FROM integrity_manifests
                   WHERE created_at < %s ORDER BY created_at DESC LIMIT 1""",
                (row["created_at"],),
            ).fetchone()
        expected_previous = str(previous["manifest_hash"]) if previous else None
        verification = self.manager.verify_manifest(
            str(row["external_anchor_ref"]),
            expected_previous_hash=expected_previous,
        )
        status = "PASS" if verification.get("valid") else "FAIL"
        event_type = "VERIFY_PASS" if verification.get("valid") else "VERIFY_FAIL"
        with self.store.connection() as conn:
            event = self._event(
                conn,
                actor=actor,
                event_type=event_type,
                status=status,
                manifest_id=manifest_id,
                detail=verification,
            )
        return {
            "contract": INTEGRITY_GOVERNANCE_CONTRACT,
            "manifest_id": manifest_id,
            "verification": verification,
            "event": event,
        }

    def anchor_existing(self, *, manifest_id: str, actor: str) -> dict[str, Any]:
        require_canonical_mutation("integrity.reanchor")
        with self.store.connection() as conn:
            row = conn.execute(
                "SELECT manifest_hash FROM integrity_manifests WHERE manifest_id=%s",
                (manifest_id,),
            ).fetchone()
            if not row:
                raise KeyError(manifest_id)
        result = self.manager.try_anchor(
            root_hash=str(row["manifest_hash"]),
            scope_type="MANIFEST_REANCHOR",
            scope_id=manifest_id,
            metadata={"parent_manifest_id": manifest_id},
        )
        if not result.get("anchored"):
            with self.store.connection() as conn:
                event = self._event(
                    conn,
                    actor=actor,
                    event_type="ANCHOR_DEGRADED",
                    status="DEGRADED",
                    manifest_id=manifest_id,
                    detail={k: v for k, v in result.items() if k != "manifest"},
                )
            return {"contract": INTEGRITY_GOVERNANCE_CONTRACT, **result, "event": event}
        manifest = dict(result["manifest"])
        verification = self.manager.verify_manifest(manifest["external_anchor_ref"])
        if not verification.get("valid"):
            raise RuntimeError("re-anchor failed immediate verification")
        with self.store.connection() as conn:
            self._persist_manifest(conn, manifest)
            event = self._event(
                conn,
                actor=actor,
                event_type="ANCHOR_CREATED",
                status="PASS",
                manifest_id=manifest["manifest_id"],
                detail={"parent_manifest_id": manifest_id, "manifest_hash": manifest["manifest_hash"]},
            )
        return {"contract": INTEGRITY_GOVERNANCE_CONTRACT, "manifest": manifest, "verification": verification, "event": event}

    def rotate_key(self, *, actor: str) -> dict[str, Any]:
        require_canonical_mutation("integrity.rotate_key")
        rotation = self.manager.rotate_key()
        with self.store.connection() as conn:
            event = self._event(
                conn,
                actor=actor,
                event_type="KEY_ROTATED",
                status="PASS",
                manifest_id=None,
                detail=rotation,
            )
        return {"contract": INTEGRITY_GOVERNANCE_CONTRACT, "rotation": rotation, "event": event}
