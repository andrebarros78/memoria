from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from memory_permanent.session_rotation import SessionRotationRepository
from memory_permanent.store import PostgresMemoryStore

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"

SAFE = {
    "streaming_critical": False,
    "upload_unconfirmed": False,
    "non_idempotent_write_pending": False,
    "tool_call_unpersisted": False,
    "last_event_confirmed": True,
    "checkpoint_possible": True,
}


def main() -> int:
    store = PostgresMemoryStore(os.environ["MEMORY_DATABASE_URL"])
    repo = SessionRotationRepository(store)
    suffix = f"{int(time.time())}"
    session_id = f"m9-proof-{suffix}"

    with store._connection() as conn:
        rows = conn.execute(
            """SELECT m.item_id FROM memory_items m JOIN memory_operator_state s ON s.item_id=m.item_id
               WHERE s.operator_class IN ('PERMANENTE','PROTEGIDA') ORDER BY m.created_at LIMIT 4"""
        ).fetchall()
    required_ids = [str(row["item_id"]) for row in rows]

    repo.create_session(
        session_id=session_id,
        identity={"agent": "m9-proof-client", "tenant": "local-proof"},
        scope="MEMORIA_PERMANENTE_V4",
        objective="Provar Session Rotation sem depender da sessão externa antiga",
        critical_rules=["fail-closed", "old-session-preserved-until-validation"],
        operational_state={"phase": "M9", "last_confirmed_step": 8},
        last_confirmed_action="GATE_M10=PASS",
        blockers=[],
        pending=["M9", "M11", "pgvector"],
        next_safe_action="rotate external client safely",
        active_authorizations=["local-runtime-proof"],
        required_memory_ids=required_ids,
    )
    old = repo.create_binding(session_id=session_id, provider="synthetic-sdk", external_session_ref=f"old-{suffix}")

    unsafe = dict(SAFE)
    unsafe["streaming_critical"] = True
    wait_rotation = repo.request_rotation(session_id=session_id, safe_point=unsafe, memory_before_mb=120.0, reason="sustained-memory-pressure")
    waiting_safe_point = wait_rotation["status"] == "WAITING_SAFE_POINT"
    ready_rotation = repo.update_safe_point(wait_rotation["rotation_id"], SAFE)
    safe_point_promoted = ready_rotation["status"] == "REQUESTED"
    prepared_bad = repo.prepare_rotation(wait_rotation["rotation_id"], last_event_id="evt-m9-bad")
    pack_bad = prepared_bad["context_pack"]
    bad_binding = repo.bind_new_external(wait_rotation["rotation_id"], provider="synthetic-sdk", external_session_ref=f"bad-{suffix}")
    bad_validation = repo.validate_rotation(
        wait_rotation["rotation_id"],
        observed_context_sha256="0" * 64,
        observed_checkpoint_id=pack_bad["checkpoint_id"],
        observed_required_memory_ids=pack_bad["required_memory_ids"],
    )
    old_after_failure = repo.current_binding(session_id)
    failure_preserved_old = (
        bad_validation["validated"] is False
        and bad_validation["rotation"]["status"] == "ABORTED"
        and old_after_failure["binding_id"] == old["binding_id"]
    )

    good_rotation = repo.request_rotation(session_id=session_id, safe_point=SAFE, memory_before_mb=120.0, reason="sustained-memory-pressure")
    prepared_good = repo.prepare_rotation(good_rotation["rotation_id"], last_event_id="evt-m9-good")
    pack_good = prepared_good["context_pack"]
    good_binding = repo.bind_new_external(good_rotation["rotation_id"], provider="synthetic-sdk", external_session_ref=f"good-{suffix}")
    validated = repo.validate_rotation(
        good_rotation["rotation_id"],
        observed_context_sha256=pack_good["context_sha256"],
        observed_checkpoint_id=pack_good["checkpoint_id"],
        observed_required_memory_ids=pack_good["required_memory_ids"],
    )
    old_before_completion = repo.current_binding(session_id)
    old_kept_until_validation = validated["validated"] is True and old_before_completion["binding_id"] == old["binding_id"]
    completed = repo.complete_rotation(
        good_rotation["rotation_id"],
        memory_after_mb=35.0,
        client_old_closed=True,
        client_close_evidence={"type": "synthetic-sdk-process", "observed_closed": True, "old_binding_id": old["binding_id"]},
    )
    current = repo.current_binding(session_id)
    completed_ok = (
        completed["status"] == "COMPLETED"
        and current["binding_id"] == good_binding["binding_id"]
        and abs(float(completed["memory_released_mb"] or 0.0) - 85.0) < 0.001
    )

    recovery_rotation = repo.request_rotation(session_id=session_id, safe_point=SAFE, memory_before_mb=40.0, reason="recovery-plan-proof")
    repo.prepare_rotation(recovery_rotation["rotation_id"], last_event_id="evt-m9-recovery")
    recovery = repo.recovery_plan()
    recovery_item = next(item for item in recovery if item["rotation"]["rotation_id"] == recovery_rotation["rotation_id"])
    recovery_plan_ok = recovery_item["recovery_action"] == "RETRY_NEW_BINDING"
    repo.abort_rotation(recovery_rotation["rotation_id"], reason="proof cleanup")

    with store._connection() as conn:
        current_count = conn.execute("SELECT count(*) AS n FROM external_session_bindings WHERE session_id=%s AND status='CURRENT'", (session_id,)).fetchone()["n"]
        bad_state = conn.execute("SELECT status FROM external_session_bindings WHERE binding_id=%s", (bad_binding["binding_id"],)).fetchone()["status"]
    single_current = int(current_count) == 1
    bad_binding_aborted = bad_state == "ABORTED"
    audit = store.verify_audit_chain()

    checks = {
        "WAITING_SAFE_POINT": waiting_safe_point,
        "SAFE_POINT_PROMOTION": safe_point_promoted,
        "CHECKPOINT_CONTEXT_PACK": bool(pack_good["checkpoint_id"] and pack_good["context_sha256"]),
        "REQUIRED_MEMORY_IDS_PRESERVED": sorted(pack_good["required_memory_ids"]) == sorted(required_ids),
        "FAILURE_PRESERVES_OLD_SESSION": failure_preserved_old,
        "BAD_NEW_BINDING_ABORTED": bad_binding_aborted,
        "OLD_KEPT_UNTIL_VALIDATION": old_kept_until_validation,
        "SUCCESSFUL_ROTATION": completed_ok,
        "SINGLE_CURRENT_BINDING": single_current,
        "RECOVERY_PLAN": recovery_plan_ok,
        "AUDIT_CHAIN": audit["ok"],
    }
    passed = all(checks.values())
    result = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "session_id": session_id,
        "required_memory_ids": required_ids,
        "old_binding_id": old["binding_id"],
        "successful_new_binding_id": good_binding["binding_id"],
        "successful_rotation_id": good_rotation["rotation_id"],
        "context_sha256": pack_good["context_sha256"],
        "checkpoint_id": pack_good["checkpoint_id"],
        "memory_before_mb": completed["memory_before_mb"],
        "memory_after_mb": completed["memory_after_mb"],
        "memory_released_mb": completed["memory_released_mb"],
        "checks": checks,
        "failed_checks": [name for name, ok in checks.items() if not ok],
        "M9_MEMORY_CORE_PROOF": "PASS" if passed else "FAIL",
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "M9_MEMORY_CORE_PROOF.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
