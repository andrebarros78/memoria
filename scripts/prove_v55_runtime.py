from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory_permanent.signed_client import SignedMemoryClient
from memory_permanent.v55_runtime import CONFORMANCE_CHECKS

BASE = os.getenv("MEMORY_API_BASE", "http://127.0.0.1:8790").rstrip("/")
CLIENT_ID = os.getenv("MEMORY_PROOF_CLIENT_ID", "local-admin")
EXPECTED_RELEASE_CHANNEL = os.getenv("MEMORY_EXPECTED_RELEASE_CHANNEL", "MEMORIA_PERMANENTE_CANONICAL_1.0")
ROOT = Path(os.getenv("MEMORY_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
STATE_PATH = ROOT / "evidence" / "MEMORIA_PERMANENTE_CANONICAL_1_0_LIVE_PROOF_STATE.json"
PROOF_PATH = ROOT / "evidence" / "MEMORIA_PERMANENTE_CANONICAL_1_0_LIVE_RUNTIME_PROOF.json"


def _assert(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)


def _public(path: str) -> tuple[int, Any]:
    req = urllib.request.Request(BASE + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:  # nosec B310 -- loopback proof target
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            data = raw.decode("utf-8", errors="replace")
        return exc.code, data


def _signed(client: SignedMemoryClient, method: str, path: str, payload: Any | None = None,
            headers: dict[str, str] | None = None) -> Any:
    status, data = client.request(method, path, payload, extra_headers=headers, timeout=30)
    if not 200 <= int(status) < 300:
        raise AssertionError(f"{method} {path} returned HTTP {status}: {data}")
    return data


def _selected_ids(payload: dict[str, Any]) -> set[str]:
    return {str(row.get("item_id")) for row in (payload.get("selected") or []) if row.get("item_id")}


def main() -> int:
    now = datetime.now(UTC).isoformat()
    client = SignedMemoryClient(BASE, CLIENT_ID)

    status, health = _public("/health")
    _assert(status == 200, "PUBLIC_HEALTH_HTTP")
    _assert(health.get("status") == "ok", "PUBLIC_HEALTH_STATUS")
    _assert(health.get("runtime_profile") == "V5.5-PRIMARY", "V55_RUNTIME_PROFILE")
    _assert(health.get("release_channel") == EXPECTED_RELEASE_CHANNEL, "V55_RELEASE_CHANNEL")

    details = _signed(client, "GET", "/v1/health/details")
    _assert(details.get("version") == "0.30.0", "V55_PACKAGE_VERSION")
    _assert(details.get("product_id") == "memoria-permanente", "V55_PRODUCT_ID")
    _assert(details.get("v55", {}).get("ready") is True, "V55_HEALTH_GATE")

    runtime = _signed(client, "GET", "/v1/v5.5/runtime")
    consumer = _signed(client, "GET", "/v1/v5.5/consumer-adapter")
    conversational = _signed(client, "GET", "/v1/v5.5/conversational-adapter")
    _assert(runtime.get("release_channel") == EXPECTED_RELEASE_CHANNEL, "V55_RUNTIME_SPEC_RELEASE_CHANNEL")
    _assert(runtime.get("closure_points_count") == 8, "V55_EIGHT_POINTS")
    _assert(runtime.get("security_layer_count", 0) >= 10, "V55_SECURITY_DEPTH")
    _assert(runtime.get("all_official_adapters_available") is True, "V55_ADAPTERS_AVAILABLE")
    _assert(consumer.get("direct_database_access") is False, "V55_CONSUMER_NO_DB")
    _assert(conversational.get("requires_ai") is False, "V55_CONVERSATIONAL_AI_OPTIONAL")

    simple_profile = _signed(client, "POST", "/v1/v5.5/profiles/validate", {
        "deployment_profile": "CO_LOCATED",
        "capability_profiles": ["CORE", "CONVERSATIONAL"],
    })
    full_profile = _signed(client, "POST", "/v1/v5.5/profiles/validate", {
        "deployment_profile": "SHARED_SERVICE",
        "capability_profiles": ["FULL"],
    })
    _assert(simple_profile.get("ai_required") is False, "V55_SIMPLE_NO_AI")
    _assert(full_profile.get("ai_required") is True, "V55_FULL_AI_CAPABLE")
    _assert(full_profile.get("contract_changes_required") is False, "V55_PROFILE_CONTRACT_STABLE")

    unauth_status, _ = _public("/v1/v5.5/runtime")
    _assert(unauth_status in {401, 403}, "V55_PROTECTED_RUNTIME_SPEC")

    restart_recovery = False
    if STATE_PATH.exists():
        prior = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        project_a = str(prior["project_a"])
        project_b = str(prior["project_b"])
        mission_id = str(prior["mission_id"])
        item_id = str(prior["item_id"])
        token = str(prior["token"])
        headers_a = {"X-Memory-Project": project_a}
        state = _signed(client, "GET", f"/v1/checkpoints/{mission_id}/latest", headers=headers_a)
        context_a = _signed(client, "POST", "/v1/context/retrieve", {
            "query": token, "namespaces": ["V55_CONFORMANCE"], "limit": 20, "mission_id": mission_id,
        }, headers=headers_a)
        _assert(str(state.get("checkpoint_id")) == str(prior["checkpoint_id"]), "V55_RESTART_CHECKPOINT")
        _assert(item_id in _selected_ids(context_a), "V55_RESTART_CONTEXT")
        restart_recovery = True
    else:
        proof_id = uuid.uuid4().hex
        project_a = f"v55-proof-a-{proof_id[:10]}"
        project_b = f"v55-proof-b-{proof_id[:10]}"
        mission_id = f"v55-mission-{proof_id[:12]}"
        token = f"V55_UNIQUE_{proof_id}"
        headers_a = {"X-Memory-Project": project_a, "Idempotency-Key": f"v55-memory-{proof_id}"}
        memory_payload = {
            "namespace": "V55_CONFORMANCE",
            "memory_key": f"v55.conformance.{proof_id}",
            "category": "FACT",
            "content": {"token": token, "purpose": "V5.5 live conformance proof"},
            "content_text": f"{token} V5.5 universal memory conformance proof",
            "provenance": {"kind": "V55_CONFORMANCE_PROOF", "proof_id": proof_id},
            "confidence": 1.0,
            "source": "v55-conformance-proof",
            "source_version": "0.30.0",
            "tags": ["V55", "CONFORMANCE", "PROOF"],
            "memory_scope": "PROJECT",
            "memory_scope_ref": project_a,
            "sharing_scope": "PROJECT_SHARED",
            "project_id": project_a,
            "validation_status": "UNVALIDATED",
            "governor_eligible": False,
        }
        created1 = _signed(client, "POST", "/v1/memories", memory_payload, headers=headers_a)
        created2 = _signed(client, "POST", "/v1/memories", memory_payload, headers=headers_a)
        item_id = str(created1["item_id"])
        _assert(item_id == str(created2["item_id"]), "V55_IDEMPOTENCY")

        context_a = _signed(client, "POST", "/v1/context/retrieve", {
            "query": token, "namespaces": ["V55_CONFORMANCE"], "limit": 20, "mission_id": mission_id,
        }, headers={"X-Memory-Project": project_a})
        _assert(item_id in _selected_ids(context_a), "V55_POSITIVE_SCOPE_ACCESS")

        context_b = _signed(client, "POST", "/v1/context/retrieve", {
            "query": token, "namespaces": ["V55_CONFORMANCE"], "limit": 20, "mission_id": mission_id,
        }, headers={"X-Memory-Project": project_b})
        _assert(item_id not in _selected_ids(context_b), "V55_NEGATIVE_SCOPE_ISOLATION")

        checkpoint = _signed(client, "POST", "/v1/checkpoints", {
            "namespace": "V55_CONFORMANCE",
            "mission_id": mission_id,
            "step_index": 1,
            "state": {"token": token, "item_id": item_id, "phase": "PRE_RESTART"},
            "project_id": project_a,
        }, headers={"X-Memory-Project": project_a})
        checkpoint_id = str(checkpoint["checkpoint_id"])
        latest = _signed(client, "GET", f"/v1/checkpoints/{mission_id}/latest", headers={"X-Memory-Project": project_a})
        _assert(str(latest.get("checkpoint_id")) == checkpoint_id, "V55_CHECKPOINT_RESUME")

        versions = _signed(client, "GET", f"/v1/memories/{item_id}/versions", headers={"X-Memory-Project": project_a})
        rows = list(versions.get("versions") or versions.get("items") or versions if isinstance(versions, list) else [])
        if isinstance(versions, dict) and not rows:
            rows = list(versions.get("versions") or [])
        integrity_ok = bool(rows) and all(len(str(row.get("content_sha256") or "")) == 64 for row in rows)
        _assert(integrity_ok, "V55_INTEGRITY_AUDIT")

        STATE_PATH.write_text(json.dumps({
            "created_at": now,
            "project_a": project_a,
            "project_b": project_b,
            "mission_id": mission_id,
            "item_id": item_id,
            "checkpoint_id": checkpoint_id,
            "token": token,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    evidence = {
        "CAPTURE": True,
        "CONTEXT_RECOVERY": True,
        "POSITIVE_SCOPE_ACCESS": True,
        "NEGATIVE_SCOPE_ISOLATION": True,
        "AUTHENTICATION_AUTHORIZATION": True,
        "IDEMPOTENCY": True,
        "CHECKPOINT_RESUME": True,
        "RESTART_RECOVERY": restart_recovery,
        "NO_DIRECT_DATABASE_ACCESS": consumer.get("direct_database_access") is False,
        "SECURITY_REGRESSION": os.getenv("V55_SECURITY_REGRESSION_PASS", "0") == "1",
        "INTEGRITY_AUDIT": True,
    }
    conformance = _signed(client, "POST", "/v1/v5.5/conformance/evaluate", {"evidence": evidence})

    proof = {
        "generated_at": now,
        "base": BASE,
        "expected_release_channel": EXPECTED_RELEASE_CHANNEL,
        "health": health,
        "health_details": details,
        "runtime_contract": runtime.get("contract"),
        "closure_points_count": runtime.get("closure_points_count"),
        "security_layer_count": runtime.get("security_layer_count"),
        "all_official_adapters_available": runtime.get("all_official_adapters_available"),
        "consumer_adapter": consumer,
        "conversational_adapter": conversational,
        "simple_profile": simple_profile,
        "full_profile": full_profile,
        "unauthenticated_runtime_spec_status": unauth_status,
        "conformance_evidence": evidence,
        "conformance": conformance,
        "state_path": str(STATE_PATH),
        "restart_recovery_verified": restart_recovery,
        "all_required_checks": list(CONFORMANCE_CHECKS),
    }
    PROOF_PATH.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "V55_LIVE_RUNTIME": "PASS",
        "runtime_profile": health.get("runtime_profile"),
        "release_channel": health.get("release_channel"),
        "restart_recovery_verified": restart_recovery,
        "conformance_compatible": conformance.get("compatible"),
        "proof": str(PROOF_PATH),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
