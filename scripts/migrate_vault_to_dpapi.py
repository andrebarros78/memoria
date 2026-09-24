from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(r"C:\New Projet\MEMORIA-PERMANENTE")
LEGACY = ROOT / "runtime" / "vault"
PROGRAM_DATA = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
TARGET = PROGRAM_DATA / "MemoriaPermanente" / "vault"
EVIDENCE = ROOT / "evidence" / "VAULT_DPAPI_MIGRATION_PROOF.json"

sys.path.insert(0, str(ROOT / "src"))
from memory_permanent.secret_sanitizer import (  # noqa: E402
    LocalEncryptedVault,
    WindowsDpapiKeyProvider,
)


def decrypt_legacy(path: Path, key: bytes) -> tuple[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nonce = base64.b64decode(payload["nonce"])
    ciphertext = base64.b64decode(payload["ciphertext"])
    aad = f"{payload['tenant_id']}:{payload['kind']}:{payload['ref']}".encode()
    value = AESGCM(key).decrypt(nonce, ciphertext, aad).decode("utf-8")
    return str(payload["ref"]), value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    legacy_key_path = LEGACY / ".master.key"
    if not legacy_key_path.exists():
        raise RuntimeError("legacy plaintext master key not found; migration already completed or state inconsistent")
    legacy_key = legacy_key_path.read_bytes()
    if len(legacy_key) != 32:
        raise RuntimeError("invalid legacy master key")

    target_key = TARGET / "vault-master.dpapi"
    TARGET.mkdir(parents=True, exist_ok=True)
    provider = WindowsDpapiKeyProvider(target_key, machine_scope=True)
    provider.protect_existing(legacy_key)

    legacy_files = sorted(LEGACY.glob("*.json"))
    copied: list[dict[str, object]] = []
    for src in legacy_files:
        ref, old_plain = decrypt_legacy(src, legacy_key)
        dst = TARGET / src.name
        shutil.copy2(src, dst)
        new_vault = LocalEncryptedVault(TARGET)
        new_plain = new_vault.get(ref)
        if old_plain != new_plain:
            raise RuntimeError(f"vault validation mismatch for {src.name}")
        copied.append({
            "name": src.name,
            "cipher_sha256": sha256_file(src),
            "cipher_bytes": src.stat().st_size,
            "reference_validated": True,
        })

    protected_key = provider.load_or_create()
    if protected_key != legacy_key:
        raise RuntimeError("DPAPI key roundtrip mismatch")

    result = {
        "migration": "PLAINTEXT_MASTER_KEY_TO_WINDOWS_DPAPI_MACHINE",
        "source_root": str(LEGACY),
        "target_root": str(TARGET),
        "target_key_file": str(target_key),
        "target_key_file_sha256": sha256_file(target_key),
        "target_key_is_dpapi_blob": target_key.stat().st_size > 32,
        "plaintext_key_inside_product_before": True,
        "vault_records_validated": len(copied),
        "records": copied,
    }
    EVIDENCE.write_text(json.dumps(result, indent=2), encoding="utf-8")

    # Best-effort removal after successful roundtrip. Never print or persist key material.
    with legacy_key_path.open("r+b", buffering=0) as f:
        f.write(os.urandom(32))
        f.flush()
        os.fsync(f.fileno())
    legacy_key_path.unlink()
    for src in legacy_files:
        src.unlink()
    try:
        LEGACY.rmdir()
    except OSError:
        pass

    result["plaintext_key_inside_product_after"] = legacy_key_path.exists()
    result["legacy_cipher_files_inside_product_after"] = len(list(LEGACY.glob("*.json"))) if LEGACY.exists() else 0
    result["PASS"] = (not result["plaintext_key_inside_product_after"] and result["legacy_cipher_files_inside_product_after"] == 0)
    EVIDENCE.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "target_root": str(TARGET),
        "vault_records_validated": len(copied),
        "plaintext_key_inside_product_after": result["plaintext_key_inside_product_after"],
        "legacy_cipher_files_inside_product_after": result["legacy_cipher_files_inside_product_after"],
        "PASS": result["PASS"],
    }, indent=2))
    return 0 if result["PASS"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
