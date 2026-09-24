from __future__ import annotations

import json
import sys
import time
import urllib.request
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
    restart_proof = json.loads((ROOT / "evidence" / "M2_RESTART_CONTINUITY_PROOF.json").read_text(encoding="utf-8-sig"))
    if restart_proof.get("M2_RESTART_CONTINUITY_PROOF") != "PASS":
        raise RuntimeError("restart continuity proof is not PASS")
    session_id = str(restart_proof["session_id"])
    before = request("POST", f"/v1/sessions/{session_id}/resume", {})
    recovery = request("GET", "/v1/session-rotations-recovery")
    candidates = [x for x in recovery.get("items", []) if (x.get("rotation") or {}).get("session_id") == session_id]
    if not candidates:
        raise RuntimeError("no incomplete rotation available for M2 provider swap")
    rotation = candidates[-1]["rotation"]
    if rotation.get("status") != "CHECKPOINTED":
        raise RuntimeError(f"expected CHECKPOINTED rotation, got {rotation.get('status')}")
    rotation_id = str(rotation["rotation_id"])
    context_pack = before["context_pack"]
    expected_context_hash = str(context_pack["context_sha256"])
    expected_checkpoint = str(context_pack["checkpoint_id"])
    expected_ids = sorted(str(x) for x in context_pack.get("required_memory_ids") or [])
    expected_objective = str((context_pack.get("context") or {}).get("objective") or "")

    with psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("SELECT set_config('app.current_tenant', %s, true)", ("LEGACY",))
        before_counts = conn.execute("SELECT count(*) AS memories FROM memory_items").fetchone()
        old_binding = conn.execute("SELECT * FROM external_session_bindings WHERE binding_id=%s", (rotation["old_binding_id"],)).fetchone()
        schema_before = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()

    openai = OpenAIProviderAdapter()
    openai_probe = openai.probe()
    ollama = OllamaProviderAdapter(model="qwen2.5-coder:3b")
    ollama_probe = ollama.probe()
    if not ollama_probe.get("model_available"):
        raise RuntimeError("qwen2.5-coder:3b not available in Ollama")

    observation = None
    errors: list[str] = []
    for attempt in range(1, 4):
        try:
            candidate = ollama.observe_context(context_pack)
            checks = (
                candidate.context_sha256 == expected_context_hash
                and candidate.checkpoint_id == expected_checkpoint
                and sorted(candidate.required_memory_ids) == expected_ids
                and candidate.objective == expected_objective
            )
            if checks:
                observation = candidate
                break
            errors.append(f"attempt {attempt}: observation mismatch")
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
        time.sleep(1)
    if observation is None:
        raise RuntimeError("Ollama did not reproduce required Context Pack fields: " + " | ".join(errors))

    binding = request("POST", f"/v1/session-rotations/{rotation_id}/bind", {
        "provider": observation.provider,
        "external_session_ref": observation.external_session_ref,
    })
    validation = request("POST", f"/v1/session-rotations/{rotation_id}/validate", {
        "observed_context_sha256": observation.context_sha256,
        "observed_checkpoint_id": observation.checkpoint_id,
        "observed_required_memory_ids": observation.required_memory_ids,
    })
    if not validation.get("validated"):
        raise RuntimeError("rotation validation failed")
    completion = request("POST", f"/v1/session-rotations/{rotation_id}/complete", {
        "memory_after_mb": 128.0,
        "client_old_closed": True,
        "client_close_evidence": {
            "proof": "M2_PROVIDER_SWAP",
            "logical_test_binding": True,
            "old_provider": "openai",
            "new_provider": observation.provider,
            "new_model": observation.model,
            "provider_response_sha256": observation.raw_response_sha256,
        },
    })
    after = request("POST", f"/v1/sessions/{session_id}/resume", {})

    with psycopg.connect(dsn(), row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("SELECT set_config('app.current_tenant', %s, true)", ("LEGACY",))
        after_counts = conn.execute("SELECT count(*) AS memories FROM memory_items").fetchone()
        old_after = conn.execute("SELECT * FROM external_session_bindings WHERE binding_id=%s", (rotation["old_binding_id"],)).fetchone()
        new_after = conn.execute("SELECT * FROM external_session_bindings WHERE binding_id=%s", (binding["binding_id"],)).fetchone()
        schema_after = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        audit_rows = conn.execute(
            "SELECT event_type,target_id AS entity_id,created_at FROM audit_events WHERE target_id IN (%s,%s,%s) ORDER BY created_at",
            (rotation_id, rotation["old_binding_id"], binding["binding_id"]),
        ).fetchall()

    checks = {
        "M2_RESTART_PROOF_ALREADY_PASS": restart_proof.get("M2_RESTART_CONTINUITY_PROOF") == "PASS",
        "OPENAI_REAL_PROVIDER_REACHABLE": bool(openai_probe.get("reachable")) and int(openai_probe.get("model_count", 0)) > 0,
        "OPENAI_PAID_INFERENCE_NOT_USED": openai_probe.get("paid_inference_used") is False,
        "OLLAMA_REAL_PROVIDER_REACHABLE": bool(ollama_probe.get("reachable")),
        "OLLAMA_TARGET_MODEL_AVAILABLE": bool(ollama_probe.get("model_available")),
        "OLLAMA_REAL_INFERENCE_EXECUTED": int(observation.metadata.get("eval_count") or 0) > 0,
        "TARGET_OBSERVED_CONTEXT_HASH": observation.context_sha256 == expected_context_hash,
        "TARGET_OBSERVED_CHECKPOINT": observation.checkpoint_id == expected_checkpoint,
        "TARGET_OBSERVED_REQUIRED_MEMORY_IDS": sorted(observation.required_memory_ids) == expected_ids,
        "TARGET_OBSERVED_OBJECTIVE": observation.objective == expected_objective,
        "ROTATION_VALIDATED": bool(validation.get("validated")),
        "ROTATION_COMPLETED": completion.get("status") == "COMPLETED",
        "SESSION_ID_UNCHANGED": after["session"]["session_id"] == session_id,
        "CHECKPOINT_UNCHANGED": after["checkpoint"]["checkpoint_id"] == expected_checkpoint,
        "CONTEXT_HASH_UNCHANGED": after["context_pack"]["context_sha256"] == expected_context_hash,
        "CURRENT_PROVIDER_IS_OLLAMA": after["current_binding"]["provider"] == "ollama",
        "NEW_BINDING_IS_CURRENT": new_after is not None and new_after["status"] == "CURRENT",
        "OLD_BINDING_IS_SUPERSEDED": old_after is not None and old_after["status"] == "SUPERSEDED",
        "MEMORY_COUNT_UNCHANGED_BY_SWAP": int(before_counts["memories"]) == int(after_counts["memories"]),
        "SCHEMA_UNCHANGED_BY_SWAP": str(schema_before["value"]) == str(schema_after["value"]) and str(schema_after["value"]).startswith("memory-") and tuple(int(x) for x in str(schema_after["value"]).split("-", 1)[1].split(".")) >= (0, 5, 0),
        "RESUME_INTEGRITY_VALID": bool(after["integrity"]["all_valid"]),
    }
    failed = [name for name, ok in checks.items() if not ok]
    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "gate": "M2",
        "proof": "PROVIDER_SWAP",
        "session_id": session_id,
        "rotation_id": rotation_id,
        "old_provider": str(old_binding["provider"] if old_binding else ""),
        "new_provider": observation.provider,
        "new_model": observation.model,
        "old_binding_id": str(rotation["old_binding_id"]),
        "new_binding_id": str(binding["binding_id"]),
        "checkpoint_id": expected_checkpoint,
        "context_sha256": expected_context_hash,
        "required_memory_ids": expected_ids,
        "openai_probe": openai_probe,
        "ollama_probe": ollama_probe,
        "ollama_observation": observation.as_dict(),
        "validation": validation,
        "completion_status": completion.get("status"),
        "audit_events": [dict(row) for row in audit_rows],
        "checks": checks,
        "failed_checks": failed,
        "M2_PROVIDER_SWAP_PROOF": "PASS" if not failed else "FAIL",
        "GATE_M2": "PASS" if not failed else "FAIL",
        "CONTINUITY_PROVEN": not failed,
    }
    evidence = ROOT / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "M2_PROVIDER_SWAP_PROOF.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Gate M2 - Provider Swap Continuity",
        "",
        f"**M2_PROVIDER_SWAP_PROOF:** {result['M2_PROVIDER_SWAP_PROOF']}",
        f"**GATE_M2:** {result['GATE_M2']}",
        "",
        f"Session: `{session_id}`",
        f"Provider swap: `openai -> {observation.provider}:{observation.model}`",
        f"Checkpoint: `{expected_checkpoint}`",
        f"Context SHA-256: `{expected_context_hash}`",
        "",
        "OpenAI was probed without paid inference. Ollama performed the real target-provider inference.",
        "Gate M6 remains separate and still requires both OpenAI and a second provider to consume the same memory without migration.",
        "",
        "## Checks",
    ] + [f"- {name}: {'PASS' if ok else 'FAIL'}" for name, ok in checks.items()]
    (evidence / "M2_PROVIDER_SWAP_PROOF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "GATE_M2": result["GATE_M2"],
        "session_id": session_id,
        "provider_swap": f"openai -> {observation.provider}:{observation.model}",
        "ollama_eval_count": observation.metadata.get("eval_count"),
        "context_sha256": expected_context_hash,
        "checkpoint_id": expected_checkpoint,
        "failed": failed,
    }, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
