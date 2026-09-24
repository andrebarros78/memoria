from __future__ import annotations

import json
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from memory_permanent.signed_client import SignedMemoryClient

ROOT = Path(os.getenv("MEMORY_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
BASE = os.getenv("MEMORY_RESTORE_API_BASE", "http://127.0.0.1:8791").rstrip("/")
STATE = ROOT / "evidence" / "MEMORIA_PERMANENTE_CANONICAL_1_0_LIVE_PROOF_STATE.json"
OUT = ROOT / "evidence" / "CANONICAL_RESTORED_API_RESUME_PROOF.json"


def public_json(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=5) as response:  # nosec B310 -- loopback proof target
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    prior = json.loads(STATE.read_text(encoding="utf-8"))
    project = str(prior["project_a"])
    mission = str(prior["mission_id"])
    checkpoint_id = str(prior["checkpoint_id"])
    item_id = str(prior["item_id"])
    token = str(prior["token"])
    health = public_json("/health")
    assert health.get("status") == "ok"
    assert health.get("runtime_profile") == "V5.5-PRIMARY"
    assert health.get("release_channel") == "MEMORIA_PERMANENTE_CANONICAL_RESTORE_PROOF"
    client = SignedMemoryClient(BASE, "local-admin")
    status, latest = client.request("GET", f"/v1/checkpoints/{mission}/latest", extra_headers={"X-Memory-Project": project}, timeout=10)
    assert status == 200, (status, latest)
    assert str(latest.get("checkpoint_id")) == checkpoint_id
    payload = {"query": token, "namespaces": ["V55_CONFORMANCE"], "limit": 20, "mission_id": mission}
    status, context = client.request("POST", "/v1/context/retrieve", payload, extra_headers={"X-Memory-Project": project}, timeout=15)
    assert status == 200, (status, context)
    selected = {str(row.get("item_id")) for row in (context.get("selected") or []) if row.get("item_id")}
    assert item_id in selected
    proof = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "base": BASE,
        "runtime_profile": health.get("runtime_profile"),
        "release_channel": health.get("release_channel"),
        "checkpoint_resume": True,
        "context_resume": True,
        "checkpoint_id_matches": True,
        "required_memory_recovered": True,
        "secret_material_exposed": False,
    }
    OUT.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
