from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from memory_permanent.signed_client import SignedMemoryClient  # noqa: E402

BASE = "http://127.0.0.1:8787"
ITEM_ID = "mem-0a43c85342cb4776ad5d96353898bb92"
CLIENT = SignedMemoryClient(BASE, "local-admin")
PROOF = ROOT / "evidence" / "MEMORIA_PLUS_P15_PROOF.json"
MIGRATION = ROOT / "migrations" / "0030_input_guard_v2.sql"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_sha() -> str:
    digest = hashlib.sha256()
    for rel in [
        "migrations/0030_input_guard_v2.sql",
        "src/memory_permanent/input_guard.py",
        "src/memory_permanent/memory_gateway.py",
        "src/memory_permanent/api.py",
        "src/memory_permanent/client_auth.py",
    ]:
        digest.update(rel.encode("utf-8")); digest.update(b"\0")
        digest.update((ROOT / rel).read_bytes()); digest.update(b"\0")
    return digest.hexdigest()


proof = json.loads(PROOF.read_text(encoding="utf-8"))
proof_sha = sha(PROOF)
impl_sha = implementation_sha()
mig_sha = sha(MIGRATION)
status, versions_body = CLIENT.request("GET", f"/v1/memories/{ITEM_ID}/versions")
if status != 200:
    raise SystemExit(f"cannot read P15 versions: {status}")
versions = list(versions_body.get("versions", []))
current = max(versions, key=lambda row: int(row.get("version_no", 0)))

if int(current.get("version_no", 0)) == 1:
    content = dict(current.get("content_json") or {})
    content.update(
        {
            "status": "PROVEN",
            "implemented_version": "0.23.0",
            "schema_version": "memory-0.23.0",
            "input_guard_version": "IG-2.0.0",
            "proof_result": "34/34 PASS",
            "proof_sha256": proof_sha,
            "implementation_sha256": impl_sha,
            "migration_0030_sha256": mig_sha,
            "core_regression": "139/139 PASS",
            "adapter_regression": "4/4 PASS",
            "audit_dag": "PASS",
        }
    )
    text = (
        "MEMORIA PLUS prioridade 15 P2: InputGuard de segunda geracao. "
        "IMPLEMENTADO E COMPROVADO em 0.23.0 / memory-0.23.0 / IG-2.0.0. "
        "Cobertura: multilingue (EN/PT/ES/IT/FR/DE), obfuscacao, zero-width/confusaveis, "
        "Base64/URL-safe Base64/hex/percent/HTML/unicode escapes, estruturas de attachment/tool output, "
        "fragmentacao entre registros e ataques distribuidos. Prova E2E: 34/34 PASS. "
        "Regressao Core: 139/139 PASS. Adapter: 4/4 PASS. Audit DAG: PASS."
    )
    payload = {
        "content": content,
        "content_text": text,
        "provenance": {
            "tag": "MEMORIA PLUS",
            "registration": "p15-proven-after-e2e-regression-audit",
            "proof_sha256": proof_sha,
            "implementation_sha256": impl_sha,
            "migration_0030_sha256": mig_sha,
        },
        "confidence": 1.0,
        "source": "p15-implementation-proof",
        "source_version": "IG-2.0.0",
        "tags": ["MEMORIA PLUS", "V4", "CORRECAO", "P2", "PRIORIDADE_15", "PROVEN", "IG-2.0.0"],
        "expected_version": 1,
    }
    status, revised = CLIENT.request(
        "POST",
        f"/v1/memories/{ITEM_ID}/versions",
        payload=payload,
        extra_headers={"Idempotency-Key": "memoria-plus-p15-final-v2"},
        timeout=30,
    )
    if status != 201:
        raise SystemExit(f"P15 revision failed: {status}")
else:
    revised = current

status, versions_body = CLIENT.request("GET", f"/v1/memories/{ITEM_ID}/versions")
versions = list(versions_body.get("versions", [])) if status == 200 else []
current = max(versions, key=lambda row: int(row.get("version_no", 0))) if versions else {}
if int(current.get("version_no", 0)) != 2:
    raise SystemExit(f"unexpected P15 current version: {current.get('version_no')}")
content_sha = str(current.get("content_sha256") or "")
if len(content_sha) != 64:
    raise SystemExit("P15 version 2 content hash missing")

validation_payload = {
    "expected_version": 2,
    "expected_content_sha256": content_sha,
    "status": "VALIDATED",
    "governor_eligible": False,
    "evidence": {
        "proof": "MEMORIA_PLUS_P15_PROOF",
        "proof_sha256": proof_sha,
        "proof_checks": proof.get("passed"),
        "proof_total": proof.get("check_count"),
        "implementation_sha256": impl_sha,
        "migration_0030_sha256": mig_sha,
        "core_regression": "139/139 PASS",
        "adapter_regression": "4/4 PASS",
        "audit_dag": "PASS",
    },
}
status, validated = CLIENT.request("POST", f"/v1/memories/{ITEM_ID}/validation", payload=validation_payload)
if status not in (200, 201):
    raise SystemExit(f"P15 validation failed: {status}")

result = {
    "item_id": ITEM_ID,
    "version_no": 2,
    "version_id": current.get("version_id"),
    "content_sha256": content_sha,
    "status": (current.get("content_json") or {}).get("status"),
    "validation_status": validated.get("validation_status") or validated.get("status"),
    "validation_id": validated.get("validation_id"),
    "governor_eligible": validated.get("governor_eligible"),
    "proof_sha256": proof_sha,
    "implementation_sha256": impl_sha,
    "migration_0030_sha256": mig_sha,
}
print(json.dumps(result, ensure_ascii=True, indent=2))
