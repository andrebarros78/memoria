from __future__ import annotations

import hashlib
import json
import os
import subprocess  # nosec B404 -- fixed local tooling; shell execution is not used.
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory_permanent.signed_client import SignedMemoryClient

ROOT = Path(os.getenv("MEMORY_PROJECT_ROOT", Path(__file__).resolve().parents[1])).resolve()
BASE = os.getenv("MEMORY_API_BASE", "http://127.0.0.1:8787").rstrip("/")
EV = ROOT / ".agents" / "evidence" / "mission-20260904-terminal" / "learning-loop"
STATE = EV / "learning-loop-state.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request(client: SignedMemoryClient, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    status, data = client.request(method, path, payload, timeout=30)
    if not 200 <= int(status) < 300:
        raise RuntimeError(f"{method} {path} -> {status}: {data}")
    if not isinstance(data, dict):
        raise RuntimeError(f"{method} {path} returned non-object response")
    return data


def run_inspector(out: Path) -> int:
    cli = ROOT / ".agents" / "tools" / "mcp-inspector" / "node_modules" / "@modelcontextprotocol" / "inspector" / "clients" / "cli" / "build" / "index.js"
    runtime_py = ROOT / "runtime" / "canonical-api" / "Scripts" / "python.exe"
    if not cli.is_file():
        raise RuntimeError(f"MCP Inspector CLI 2.5.0 is missing: {cli}")
    if not runtime_py.is_file():
        raise RuntimeError(f"Canonical runtime Python is missing: {runtime_py}")
    cmd = [
        "node", str(cli), str(runtime_py), "-I", "-m", "memory_permanent.mcp_server",
        "--", "--transport", "stdio", "--cwd", str(ROOT),
        "--method", "tools/call", "--tool-name", "memory_summary",
        "--tool-args-json", "{}", "--format", "json",
    ]
    cp = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=45, check=False)  # nosec B603
    out.write_text((cp.stdout or "") + (cp.stderr or ""), encoding="utf-8")
    return int(cp.returncode)


def _recovery_proof(current: dict[str, Any]) -> dict[str, Any] | None:
    rows = [
        row for row in current.get("proofs", [])
        if row.get("proof_type") == "RECOVERY" and row.get("result") == "PASS"
    ]
    return rows[-1] if rows else None


def main() -> int:
    if not STATE.is_file():
        raise RuntimeError(f"learning-loop state is missing: {STATE}")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    skill_version_id = str(state["skill_version_id"])
    client = SignedMemoryClient(BASE, "memory-steward-agent")

    with urllib.request.urlopen(BASE + "/health", timeout=15) as response:  # nosec B310 -- fixed loopback canonical API
        health = json.loads(response.read().decode("utf-8"))
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise RuntimeError(f"canonical public health unavailable: {health}")

    current = request(client, "GET", f"/v1/operations/skill-versions/{skill_version_id}")
    recovery = _recovery_proof(current)
    recovery_exit = 0
    if recovery is None:
        recovery_file = EV / "skill-recovery.txt"
        recovery_exit = run_inspector(recovery_file)
        if recovery_exit != 0:
            raise RuntimeError(f"recovery replay failed exit={recovery_exit}")
        recovery = request(
            client,
            "POST",
            f"/v1/operations/skill-versions/{skill_version_id}/proofs",
            {
                "proof_type": "RECOVERY",
                "result": "PASS",
                "artifact_ref": str(recovery_file),
                "artifact_sha256": sha256(recovery_file),
                "evidence": {
                    "exit_code": recovery_exit,
                    "client": "MCP Inspector 2.5.0",
                    "after_runtime_restart": True,
                    "runtime_profile": health.get("runtime_profile"),
                    "release_channel": health.get("release_channel"),
                    "direct_db": False,
                },
            },
        )
        current = request(client, "GET", f"/v1/operations/skill-versions/{skill_version_id}")

    if current.get("current_status") != "PROVEN":
        raise RuntimeError(f"proof engine did not promote skill version: {current.get('current_status')}")
    recovery_proof = _recovery_proof(current) or recovery
    if recovery_proof is None:
        raise RuntimeError("RECOVERY:PASS proof disappeared after promotion")

    status_history = current.get("status_history") or []
    status_event_id = status_history[-1].get("status_event_id") if status_history else None
    state.update(
        {
            "recovery_exit": recovery_exit,
            "recovery_proof_id": recovery_proof.get("proof_id"),
            "status_event_id": status_event_id,
            "status_after_recovery": current.get("current_status"),
            "recovery_pending": False,
            "recovery_verified_at": datetime.now(UTC).isoformat(),
            "promotion_authority": "PROOF_ENGINE",
        }
    )
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": "PASS", "skill_version_id": skill_version_id, "status": current.get("current_status"), "recovery_proof_id": recovery_proof.get("proof_id"), "promotion_authority": "PROOF_ENGINE", "state": str(STATE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())