from __future__ import annotations

import concurrent.futures
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory_permanent.signed_client import SignedMemoryClient

ROOT = Path(os.getenv("MEMORY_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
BASE = os.getenv("MEMORY_API_BASE", "http://127.0.0.1:8790").rstrip("/")
CLIENT_ID = os.getenv("MEMORY_PROOF_CLIENT_ID", "local-admin")
DURATION = max(30, min(int(os.getenv("CANONICAL_ENDURANCE_SECONDS", "30")), 120))
MIN_WRITES = max(100, min(int(os.getenv("CANONICAL_ENDURANCE_MIN_WRITES", "120")), 300))
PROOF_PATH = ROOT / "evidence" / "CANONICAL_ENDURANCE_PROOF.json"


def signed(method: str, path: str, payload: Any | None = None, headers: dict[str, str] | None = None, timeout: int = 15) -> Any:
    client = SignedMemoryClient(BASE, CLIENT_ID)
    status, data = client.request(method, path, payload, extra_headers=headers, timeout=timeout)
    if not 200 <= int(status) < 300:
        raise RuntimeError(f"{method} {path} -> HTTP {status}: {data}")
    return data


def public_status(path: str) -> int:
    req = urllib.request.Request(BASE + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:  # nosec B310 -- loopback proof target
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def verify_item(args: tuple[str, str]) -> bool:
    project_id, item_id = args
    data = signed("GET", f"/v1/memories/{item_id}/versions", headers={"X-Memory-Project": project_id}, timeout=10)
    rows = data if isinstance(data, list) else (data.get("versions") or data.get("items") or [])
    return bool(rows) and all(len(str(row.get("content_sha256") or "")) == 64 for row in rows)


def main() -> int:
    proof_id = uuid.uuid4().hex
    project_a = f"scope-seal-a-{proof_id[:12]}"
    project_b = f"scope-seal-b-{proof_id[:12]}"
    mission_id = f"scope-seal-mission-{proof_id[:12]}"
    token = f"CANONICAL_ENDURANCE_{proof_id}"
    errors: list[str] = []
    item_ids: list[str] = []
    context_reads = 0
    health_checks = 0
    checkpoints = 0
    idempotency_checks = 0
    start = time.monotonic()
    i = 0

    while time.monotonic() - start < DURATION or i < MIN_WRITES:
        i += 1
        item_token = f"CANONICAL_ITEM_{uuid.uuid5(uuid.NAMESPACE_OID, f'{proof_id}:{i}').hex}"
        payload = {
            "namespace": "CANONICAL_SCOPE_SEAL",
            "memory_key": f"scope_seal.endurance.{proof_id}.{i:04d}",
            "category": "EVIDENCE",
            "content": {"token": token, "item_token": item_token, "index": i, "purpose": "canonical endurance scope seal"},
            "content_text": f"{item_token} {token} canonical endurance evidence index {i}",
            "provenance": {"kind": "CANONICAL_SCOPE_SEAL_ENDURANCE", "proof_id": proof_id, "index": i},
            "confidence": 1.0,
            "source": "canonical-scope-seal-endurance",
            "source_version": "0.30.0",
            "tags": ["CANONICAL", "SCOPE_SEAL", "ENDURANCE"],
            "memory_scope": "PROJECT",
            "memory_scope_ref": project_a,
            "sharing_scope": "PROJECT_SHARED",
            "project_id": project_a,
            "validation_status": "UNVALIDATED",
            "governor_eligible": False,
        }
        idem = f"scope-seal-{proof_id}-{i}"
        try:
            created = signed("POST", "/v1/memories", payload, headers={"X-Memory-Project": project_a, "Idempotency-Key": idem})
            item_id = str(created["item_id"])
            item_ids.append(item_id)
            if i in {1, 25, 50, 75, 100}:
                duplicate = signed("POST", "/v1/memories", payload, headers={"X-Memory-Project": project_a, "Idempotency-Key": idem})
                if str(duplicate.get("item_id")) != item_id:
                    errors.append(f"idempotency_mismatch_{i}")
                else:
                    idempotency_checks += 1
            if i % 10 == 0:
                ctx = signed("POST", "/v1/context/retrieve", {"query": item_token, "namespaces": ["CANONICAL_SCOPE_SEAL"], "limit": 20, "mission_id": mission_id}, headers={"X-Memory-Project": project_a}, timeout=20)
                selected = {str(x.get("item_id")) for x in (ctx.get("selected") or [])}
                if item_id not in selected:
                    errors.append(f"context_missing_{i}")
                context_reads += 1
            if i % 20 == 0:
                with urllib.request.urlopen(BASE + "/health", timeout=5) as response:  # nosec B310 -- loopback proof target
                    health = json.loads(response.read().decode("utf-8"))
                if health.get("status") != "ok" or health.get("release_channel") != "MEMORIA_PERMANENTE_CANONICAL_1.0":
                    errors.append(f"health_identity_{i}")
                health_checks += 1
            if i % 25 == 0:
                cp = signed("POST", "/v1/checkpoints", {
                    "namespace": "CANONICAL_SCOPE_SEAL",
                    "mission_id": mission_id,
                    "step_index": i,
                    "state": {"token": token, "last_item_id": item_id, "writes": i},
                    "project_id": project_a,
                }, headers={"X-Memory-Project": project_a})
                if not cp.get("checkpoint_id"):
                    errors.append(f"checkpoint_missing_{i}")
                checkpoints += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"write_loop_{i}:{type(exc).__name__}:{str(exc)[:300]}")
            break

    elapsed = time.monotonic() - start
    unique_ids = len(set(item_ids))
    versions_ok = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(verify_item, (project_a, item_id)) for item_id in item_ids]
        for fut in concurrent.futures.as_completed(futures):
            try:
                if fut.result():
                    versions_ok += 1
                else:
                    errors.append("version_integrity_false")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"version_verify:{type(exc).__name__}:{str(exc)[:250]}")

    latest = signed("GET", f"/v1/checkpoints/{mission_id}/latest", headers={"X-Memory-Project": project_a}) if checkpoints else {}
    negative = signed("POST", "/v1/context/retrieve", {"query": token, "namespaces": ["CANONICAL_SCOPE_SEAL"], "limit": 50, "mission_id": mission_id}, headers={"X-Memory-Project": project_b}, timeout=20)
    negative_ids = {str(x.get("item_id")) for x in (negative.get("selected") or [])}
    isolation_ok = not bool(negative_ids.intersection(item_ids))
    unauth = public_status("/v1/v5.5/runtime")

    checks = {
        "DURATION_REACHED": elapsed >= DURATION * 0.98,
        "MINIMUM_WRITES_REACHED": len(item_ids) >= MIN_WRITES,
        "ZERO_OPERATION_ERRORS": not errors,
        "UNIQUE_ITEM_IDS": unique_ids == len(item_ids),
        "ALL_VERSIONS_INTEGRITY_OK": versions_ok == len(item_ids),
        "CONTEXT_READS_EXECUTED": context_reads >= max(1, MIN_WRITES // 20),
        "HEALTH_CHECKS_EXECUTED": health_checks >= max(1, MIN_WRITES // 40),
        "CHECKPOINTS_EXECUTED": checkpoints >= max(1, MIN_WRITES // 50),
        "LATEST_CHECKPOINT_RESUMABLE": bool(latest.get("checkpoint_id")),
        "IDEMPOTENCY_PROVEN": idempotency_checks >= 4,
        "NEGATIVE_SCOPE_ISOLATION": isolation_ok,
        "UNAUTHENTICATED_PROTECTED_ENDPOINT_DENIED": unauth in {401, 403},
    }
    failed = [name for name, ok in checks.items() if not ok]
    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "proof": "CANONICAL_ENDURANCE_AND_CONCURRENT_READBACK",
        "base": BASE,
        "duration_target_seconds": DURATION,
        "elapsed_seconds": round(elapsed, 3),
        "minimum_writes": MIN_WRITES,
        "writes_created": len(item_ids),
        "unique_item_ids": unique_ids,
        "versions_verified": versions_ok,
        "context_reads": context_reads,
        "health_checks": health_checks,
        "checkpoints": checkpoints,
        "idempotency_checks": idempotency_checks,
        "negative_scope_isolation": isolation_ok,
        "unauthenticated_runtime_status": unauth,
        "checks": checks,
        "failed_checks": failed,
        "errors": errors[:20],
        "status": "PASS" if not failed else "FAIL",
        "project_a": project_a,
        "project_b": project_b,
        "mission_id": mission_id,
        "sample_item_ids": item_ids[:5],
        "latest_checkpoint_id": latest.get("checkpoint_id"),
    }
    PROOF_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "elapsed_seconds", "writes_created", "versions_verified", "context_reads", "health_checks", "checkpoints", "idempotency_checks", "negative_scope_isolation", "failed_checks")}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
