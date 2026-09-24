from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(r"C:\New Projet\MEMORIA-PERMANENTE")
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory_permanent.provider_adapter import (  # noqa: E402
    OllamaProviderAdapter,
    OpenAIProviderAdapter,
)

API = "http://127.0.0.1:8787"


def request(method: str, path: str, payload: dict | None = None, timeout: float = 60.0):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def dsn() -> str:
    host, port, database, user, password = (ROOT / "runtime" / "secrets" / "pgpass.conf").read_text(encoding="ascii").strip().split(":", 4)
    return f"host={host} port={port} dbname={database} user={user} password={password} connect_timeout=5"


def main() -> int:
    restart = json.loads((ROOT / "evidence" / "M2_RESTART_CONTINUITY_PROOF.json").read_text(encoding="utf-8-sig"))
    session_id = str(restart["session_id"])
    resume = request("POST", f"/v1/sessions/{session_id}/resume", {})
    context_pack = resume["context_pack"]
    expected_hash = str(context_pack["context_sha256"])
    expected_checkpoint = str(context_pack["checkpoint_id"])
    expected_ids = sorted(str(x) for x in context_pack.get("required_memory_ids") or [])
    expected_objective = str((context_pack.get("context") or {}).get("objective") or "")

    with psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=5) as conn:
        rotation = conn.execute("SELECT * FROM session_rotations WHERE session_id=%s ORDER BY requested_at DESC LIMIT 1", (session_id,)).fetchone()
        if not rotation:
            raise RuntimeError("M2 rotation not found")
        old_binding = conn.execute("SELECT * FROM external_session_bindings WHERE binding_id=%s", (rotation["old_binding_id"],)).fetchone()
        new_binding = conn.execute("SELECT * FROM external_session_bindings WHERE binding_id=%s", (rotation["new_binding_id"],)).fetchone()
        audits = conn.execute(
            "SELECT seq,event_type,target_id,payload,previous_hash,event_hash,created_at FROM audit_events WHERE target_id=%s ORDER BY seq",
            (rotation["rotation_id"],),
        ).fetchall()
        schema = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()

    openai_probe = OpenAIProviderAdapter().probe()
    ollama_adapter = OllamaProviderAdapter(model="qwen2.5-coder:3b")
    ollama_probe = ollama_adapter.probe()
    observation = ollama_adapter.observe_context(context_pack)

    audit_by_type = {str(row["event_type"]): row for row in audits}
    validated_payload = dict((audit_by_type.get("SESSION_ROTATION_VALIDATED") or {}).get("payload") or {})
    original_close = dict(rotation["client_close_evidence"] or {})

    chain_ok = True
    for prev, cur in zip(audits, audits[1:], strict=False):
        if str(cur["previous_hash"]) != str(prev["event_hash"]):
            chain_ok = False
            break

    required_sequence = [
        "SESSION_ROTATION_REQUESTED",
        "SESSION_ROTATION_CHECKPOINTED",
        "SESSION_ROTATION_NEW_BOUND",
        "SESSION_ROTATION_VALIDATED",
        "SESSION_ROTATION_COMPLETED",
    ]
    actual_sequence = [str(row["event_type"]) for row in audits]
    validation_checks = dict(validated_payload.get("checks") or {})

    checks = {
        "RESTART_PROOF_PASS": restart.get("M2_RESTART_CONTINUITY_PROOF") == "PASS",
        "API_RESUME_INTEGRITY_PASS": bool(resume.get("integrity", {}).get("all_valid")),
        "ROTATION_COMPLETED": rotation["status"] == "COMPLETED",
        "OLD_PROVIDER_WAS_OPENAI": old_binding is not None and old_binding["provider"] == "openai",
        "OLD_BINDING_SUPERSEDED": old_binding is not None and old_binding["status"] == "SUPERSEDED",
        "NEW_PROVIDER_IS_OLLAMA": new_binding is not None and new_binding["provider"] == "ollama",
        "NEW_BINDING_CURRENT": new_binding is not None and new_binding["status"] == "CURRENT",
        "SAME_SOVEREIGN_SESSION_AFTER_SWAP": resume["session"]["session_id"] == session_id,
        "SAME_CHECKPOINT_AFTER_SWAP": resume["checkpoint"]["checkpoint_id"] == expected_checkpoint == str(rotation["checkpoint_id"]),
        "SAME_CONTEXT_PACK_AFTER_SWAP": resume["context_pack"]["context_pack_id"] == str(rotation["context_pack_id"]),
        "SAME_CONTEXT_HASH_AFTER_SWAP": resume["context_pack"]["context_sha256"] == expected_hash,
        "OPENAI_REAL_ACCOUNT_REACHABLE": bool(openai_probe.get("reachable")) and int(openai_probe.get("model_count", 0)) > 0,
        "OPENAI_PAID_INFERENCE_NOT_USED": openai_probe.get("paid_inference_used") is False,
        "OLLAMA_REAL_RUNTIME_REACHABLE": bool(ollama_probe.get("reachable")),
        "OLLAMA_MODEL_AVAILABLE": bool(ollama_probe.get("model_available")),
        "OLLAMA_INFERENCE_EXECUTED_NOW": int(observation.metadata.get("eval_count") or 0) > 0,
        "OLLAMA_OBSERVED_CONTEXT_HASH": observation.context_sha256 == expected_hash,
        "OLLAMA_OBSERVED_CHECKPOINT": observation.checkpoint_id == expected_checkpoint,
        "OLLAMA_OBSERVED_REQUIRED_MEMORY_IDS": sorted(observation.required_memory_ids) == expected_ids,
        "OLLAMA_OBSERVED_OBJECTIVE": observation.objective == expected_objective,
        "ORIGINAL_VALIDATION_CONTEXT_HASH_PASS": validation_checks.get("context_sha256") is True,
        "ORIGINAL_VALIDATION_CHECKPOINT_PASS": validation_checks.get("checkpoint_id") is True,
        "ORIGINAL_VALIDATION_MEMORY_IDS_PASS": validation_checks.get("required_memory_ids") is True,
        "ORIGINAL_PROVIDER_SWAP_EVIDENCE_PRESENT": original_close.get("proof") == "M2_PROVIDER_SWAP" and original_close.get("new_provider") == "ollama" and original_close.get("old_provider") == "openai",
        "ORIGINAL_PROVIDER_RESPONSE_HASH_PRESENT": len(str(original_close.get("provider_response_sha256") or "")) == 64,
        "AUDIT_SEQUENCE_COMPLETE": actual_sequence == required_sequence,
        "AUDIT_CHAIN_CONTIGUOUS": chain_ok,
        "SCHEMA_MEMORY_0_5_0": schema is not None and schema["value"] == "memory-0.5.0",
    }
    failed = [k for k, v in checks.items() if not v]
    result = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "gate": "M2",
        "session_id": session_id,
        "rotation_id": str(rotation["rotation_id"]),
        "old_binding_id": str(old_binding["binding_id"] if old_binding else ""),
        "new_binding_id": str(new_binding["binding_id"] if new_binding else ""),
        "provider_swap": "openai -> ollama:qwen2.5-coder:3b",
        "checkpoint_id": expected_checkpoint,
        "context_pack_id": str(rotation["context_pack_id"]),
        "context_sha256": expected_hash,
        "required_memory_ids": expected_ids,
        "restart_proof": restart.get("M2_RESTART_CONTINUITY_PROOF"),
        "openai_probe": openai_probe,
        "ollama_probe": ollama_probe,
        "ollama_revalidation": observation.as_dict(),
        "original_client_close_evidence": original_close,
        "audit_sequence": actual_sequence,
        "audit_hashes": [
            {
                "seq": int(row["seq"]),
                "event_type": str(row["event_type"]),
                "previous_hash": str(row["previous_hash"]),
                "event_hash": str(row["event_hash"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in audits
        ],
        "checks": checks,
        "failed_checks": failed,
        "M2_PROVIDER_SWAP_PROOF": "PASS" if not failed else "FAIL",
        "GATE_M2": "PASS" if not failed else "FAIL",
        "CONTINUITY_PROVEN": not failed,
    }
    evidence = ROOT / "evidence"
    (evidence / "M2_PROVIDER_SWAP_PROOF.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Gate M2 - Continuity",
        "",
        f"**GATE_M2:** {result['GATE_M2']}",
        f"**CONTINUITY_PROVEN:** {result['CONTINUITY_PROVEN']}",
        "",
        f"Session: `{session_id}`",
        f"Restart proof: `{result['restart_proof']}`",
        f"Provider swap: `{result['provider_swap']}`",
        f"Checkpoint: `{expected_checkpoint}`",
        f"Context Pack: `{result['context_pack_id']}`",
        f"Context SHA-256: `{expected_hash}`",
        "",
        "OpenAI was authenticated/probed without paid inference. Ollama performed real local inference and reproduced the required Context Pack fields.",
        "M6 remains a separate gate and is not claimed by this proof.",
        "",
        "## Checks",
    ] + [f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in checks.items()]
    (evidence / "M2_GATE_PROOF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "GATE_M2": result["GATE_M2"],
        "CONTINUITY_PROVEN": result["CONTINUITY_PROVEN"],
        "provider_swap": result["provider_swap"],
        "ollama_eval_count": observation.metadata.get("eval_count"),
        "context_sha256": expected_hash,
        "audit_sequence": actual_sequence,
        "failed": failed,
    }, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
