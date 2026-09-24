from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(r"C:\New Projet\MEMORIA-PERMANENTE")
PROGRAM_DATA = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
AUTH_ROOT = PROGRAM_DATA / "MemoriaPermanente" / "auth"
CLIENT_DIR = AUTH_ROOT / "clients"
REGISTRY = AUTH_ROOT / "clients.json"
GOVERNOR_AUTH_ROOT = PROGRAM_DATA / "GovernorWindows" / "memory-auth"
GOVERNOR_SECRET = GOVERNOR_AUTH_ROOT / "governor-runtime.dpapi"
EVIDENCE = ROOT / "evidence" / "CLIENT_AUTH_PROVISIONING_PROOF.json"

import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "src"))
from memory_permanent.client_auth import CLIENT_AUTH_ENTROPY  # noqa: E402
from memory_permanent.secret_sanitizer import WindowsDpapiKeyProvider  # noqa: E402

CLIENTS = {
    "local-admin": {
        "status": "ACTIVE", "permissions": ["*"], "tenants": ["*"], "agents": ["*"],
        "users": ["*"], "projects": ["*"], "teams": ["*"], "organizations": ["*"],
        "default_tenant": "LEGACY", "default_agent": "local-admin",
    },
    "chatgpt-capture": {
        "status": "ACTIVE", "permissions": ["conversation:ingest"], "tenants": ["LEGACY"],
        "agents": ["chatgpt-capture"], "users": [], "projects": ["*"], "teams": [], "organizations": [],
        "default_tenant": "LEGACY", "default_agent": "chatgpt-capture",
    },
    "governor-runtime": {
        "status": "ACTIVE", "permissions": ["memory:read", "memory:write", "memory:context"],
        "tenants": ["LEGACY"], "agents": ["governor-windows"], "users": [], "projects": ["*"],
        "teams": [], "organizations": [], "default_tenant": "LEGACY", "default_agent": "governor-windows",
    },
    "wmcp-memory-bridge": {
        "status": "ACTIVE", "permissions": ["memory:context"], "tenants": ["LEGACY"],
        "agents": ["wmcp-memory-bridge"], "users": [], "projects": ["*"], "teams": [], "organizations": [],
        "default_tenant": "LEGACY", "default_agent": "wmcp-memory-bridge",
    },
    "mcp-memory-reader": {
        "status": "ACTIVE", "permissions": ["memory:read", "memory:context"], "tenants": ["LEGACY"],
        "agents": ["mcp-memory-reader"], "users": [], "projects": ["*"], "teams": [], "organizations": [],
        "default_tenant": "LEGACY", "default_agent": "mcp-memory-reader",
    },
    "memory-steward-agent": {
        "status": "ACTIVE", "permissions": ["memory:read", "memory:experience", "memory:operational"],
        "tenants": ["LEGACY"], "agents": ["memory-steward-agent"], "users": [], "projects": ["*"],
        "teams": [], "organizations": [], "default_tenant": "LEGACY", "default_agent": "memory-steward-agent",
    },
    "recovery-integrity-agent": {
        "status": "ACTIVE", "permissions": ["memory:read"],
        "tenants": ["LEGACY"], "agents": ["recovery-integrity-agent"], "users": [], "projects": ["*"],
        "teams": [], "organizations": [], "default_tenant": "LEGACY", "default_agent": "recovery-integrity-agent",
    },
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    CLIENT_DIR.mkdir(parents=True, exist_ok=True)
    GOVERNOR_AUTH_ROOT.mkdir(parents=True, exist_ok=True)
    registry = {"version": 1, "clients": {}}
    proof_clients = []
    for client_id, claims in CLIENTS.items():
        secret_path = CLIENT_DIR / f"{client_id}.dpapi"
        provider = WindowsDpapiKeyProvider(secret_path, machine_scope=True, entropy=CLIENT_AUTH_ENTROPY)
        secret = provider.load_or_create()
        if len(secret) != 32:
            raise RuntimeError(f"invalid secret length for {client_id}")
        if client_id == "governor-runtime":
            WindowsDpapiKeyProvider(GOVERNOR_SECRET, machine_scope=True, entropy=CLIENT_AUTH_ENTROPY).protect_existing(secret)
        row = dict(claims)
        row["secret_file"] = f"clients/{client_id}.dpapi"
        registry["clients"][client_id] = row
        proof_clients.append({
            "client_id": client_id,
            "permissions": row["permissions"],
            "tenants": row["tenants"],
            "projects": row["projects"],
            "secret_blob_bytes": secret_path.stat().st_size,
            "secret_blob_sha256": sha(secret_path),
            "secret_material_exposed": False,  # nosec B105 -- boolean evidence/status field, not a credential.
            "consumer_mirror": (str(GOVERNOR_SECRET) if client_id == "governor-runtime" else None),
            "consumer_mirror_sha256": (sha(GOVERNOR_SECRET) if client_id == "governor-runtime" else None),
        })
    tmp = REGISTRY.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, REGISTRY)
    proof = {
        "auth_scheme": "MEMORY-HMAC-SHA256-V1", "registry": str(REGISTRY), "registry_sha256": sha(REGISTRY),
        "secrets_storage": "WINDOWS_DPAPI_MACHINE", "clients": proof_clients, "PASS": True,  # nosec B105 -- boolean evidence/status field, not a credential.
    }
    EVIDENCE.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print(json.dumps({"auth_scheme": proof["auth_scheme"], "client_ids": [x["client_id"] for x in proof_clients],
                      "registry_sha256": proof["registry_sha256"], "secrets_storage": proof["secrets_storage"],
                      "governor_mirror_present": GOVERNOR_SECRET.exists(), "PASS": True}, indent=2))  # nosec B105 -- boolean evidence/status field, not a credential.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
