from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .secret_sanitizer import (
    platform_key_provider,
    platform_key_reference,
    platform_protected_key_path,
)

BACKUP_CRYPTO_VERSION = "BCP-1.0.0"
MAGIC = b"MPB1"
NONCE_BYTES = 12
TAG_BYTES = 16
BACKUP_KEY_ENTROPY = b"MEMORIA-PERMANENTE:BACKUP:BCP1"
MANIFEST_KEY_ENTROPY = b"MEMORIA-PERMANENTE:BACKUP-MANIFEST:BCP1"
SAFE_METADATA_KEYS = frozenset({
    "schema", "release", "database", "pg_dump_version", "restore_catalog_entries",
    "row_security", "tenant_context", "purpose", "backup_policy",
    "acl_preserved", "owner_preserved", "postgresql", "pgvector",
    "migration_count", "latest_migration",
})


class BackupKeyShredded(RuntimeError):
    pass


def _program_data() -> Path:
    if os.name == "nt":
        return Path(os.getenv("ProgramData", r"C:\ProgramData"))
    return Path("/var/lib")


def default_backup_key_root() -> Path:
    value = os.getenv("MEMORY_BACKUP_KEY_ROOT", "").strip()
    return Path(value) if value else _program_data() / "MemoriaPermanente" / "backup-keys"


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_manifest_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(metadata or {})
    unknown = sorted(set(source) - SAFE_METADATA_KEYS)
    if unknown:
        raise ValueError("unsafe backup manifest metadata keys: " + ",".join(unknown))
    clean: dict[str, Any] = {}
    for key, value in source.items():
        if isinstance(value, bool) or value is None or isinstance(value, (int, float)):
            clean[key] = value
            continue
        text = str(value)
        if len(text) > 500 or any(ch in text for ch in ("\r", "\n", "\x00")):
            raise ValueError(f"unsafe backup manifest metadata value: {key}")
        clean[key] = text
    return clean


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class BackupCryptoManager:
    def __init__(self, key_root: Path | None = None) -> None:
        self.key_root = Path(key_root) if key_root else default_backup_key_root()
        self.key_root.mkdir(parents=True, exist_ok=True)
        self.manifest_key = platform_key_provider(
            platform_protected_key_path(self.key_root, "manifest-signing"), machine_scope=True, entropy=MANIFEST_KEY_ENTROPY
        ).load_or_create()

    def _key_path(self, backup_id: str) -> Path:
        clean = "".join(ch for ch in str(backup_id) if ch.isalnum() or ch in "-_")
        if not clean or clean != backup_id:
            raise ValueError("invalid backup_id")
        return platform_protected_key_path(self.key_root, clean)

    def _sign_manifest(self, value: dict[str, Any]) -> str:
        body = dict(value)
        body.pop("manifest_hmac_sha256", None)
        return hmac.new(self.manifest_key, canonical(body), hashlib.sha256).hexdigest()

    def write_manifest(self, path: Path, value: dict[str, Any]) -> dict[str, Any]:
        payload = dict(value)
        payload["manifest_hmac_sha256"] = self._sign_manifest(payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        return payload

    def read_manifest(self, path: Path, *, verify: bool = True) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if verify:
            expected = str(payload.get("manifest_hmac_sha256") or "")
            actual = self._sign_manifest(payload)
            if not expected or not hmac.compare_digest(expected, actual):
                raise RuntimeError("backup manifest authentication failed")
        return payload
    def encrypt_dump(
        self, *, dump_path: Path, encrypted_path: Path, manifest_path: Path, backup_id: str,
        generated_at: datetime | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        generated = (generated_at or datetime.now(UTC)).astimezone(UTC)
        key = secrets.token_bytes(32)
        key_path = self._key_path(backup_id)
        if key_path.exists():
            raise FileExistsError(f"backup key already exists: {backup_id}")
        platform_key_provider(key_path, machine_scope=True, entropy=BACKUP_KEY_ENTROPY).protect_existing(key)
        nonce = secrets.token_bytes(NONCE_BYTES)
        encrypted_path.parent.mkdir(parents=True, exist_ok=True)
        encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        try:
            with dump_path.open("rb") as src, encrypted_path.open("wb") as dst:
                dst.write(MAGIC)
                dst.write(nonce)
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    dst.write(encryptor.update(chunk))
                encryptor.finalize()
                dst.write(encryptor.tag)
        except Exception:
            key_path.unlink(missing_ok=True)
            encrypted_path.unlink(missing_ok=True)
            raise
        payload = {
            "backup_id": backup_id,
            "generated_at": generated.isoformat(),
            "crypto_version": BACKUP_CRYPTO_VERSION,
            "cipher": "AES-256-GCM",
            "encrypted_file": str(encrypted_path),
            "encrypted_bytes": encrypted_path.stat().st_size,
            "ciphertext_sha256": sha256_file(encrypted_path),
            "key_ref": platform_key_reference("backup-keys", backup_id),
            "key_state": "ACTIVE",
            "plaintext_retained": False,
            "metadata": safe_manifest_metadata(metadata),
        }
        return self.write_manifest(manifest_path, payload)

    def decrypt_backup(self, *, manifest_path: Path, output_path: Path) -> Path:
        manifest = self.read_manifest(manifest_path)
        backup_id = str(manifest["backup_id"])
        if str(manifest.get("key_state")) != "ACTIVE":
            raise BackupKeyShredded(f"backup key is {manifest.get('key_state')}")
        key_path = self._key_path(backup_id)
        if not key_path.exists():
            raise BackupKeyShredded("backup key material is absent")
        key = platform_key_provider(key_path, machine_scope=True, entropy=BACKUP_KEY_ENTROPY).load_or_create()
        encrypted = Path(str(manifest["encrypted_file"]))
        if sha256_file(encrypted) != str(manifest["ciphertext_sha256"]):
            raise RuntimeError("encrypted backup hash mismatch")
        total = encrypted.stat().st_size
        if total < len(MAGIC) + NONCE_BYTES + TAG_BYTES:
            raise RuntimeError("encrypted backup is truncated")
        with encrypted.open("rb") as src:
            if src.read(len(MAGIC)) != MAGIC:
                raise RuntimeError("encrypted backup magic mismatch")
            nonce = src.read(NONCE_BYTES)
            src.seek(-TAG_BYTES, os.SEEK_END)
            tag = src.read(TAG_BYTES)
            ciphertext_len = total - len(MAGIC) - NONCE_BYTES - TAG_BYTES
            src.seek(len(MAGIC) + NONCE_BYTES)
            decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with output_path.open("wb") as dst:
                    remaining = ciphertext_len
                    while remaining:
                        chunk = src.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise RuntimeError("encrypted backup truncated during decrypt")
                        remaining -= len(chunk)
                        dst.write(decryptor.update(chunk))
                    decryptor.finalize()
            except Exception:
                output_path.unlink(missing_ok=True)
                raise
        return output_path

    def shred_key(self, manifest_path: Path, *, reason: str) -> dict[str, Any]:
        manifest = self.read_manifest(manifest_path)
        backup_id = str(manifest["backup_id"])
        key_path = self._key_path(backup_id)
        existed = key_path.exists()
        key_path.unlink(missing_ok=True)
        manifest["key_state"] = "SHREDDED"
        manifest["key_shredded_at"] = datetime.now(UTC).isoformat()
        manifest["key_shred_reason"] = str(reason)[:500]
        manifest = self.write_manifest(manifest_path, manifest)
        return {"backup_id": backup_id, "key_existed": existed, "key_state": "SHREDDED"}

    def shred_before(self, manifests_root: Path, *, cutoff: datetime, reason: str) -> dict[str, Any]:
        cutoff_utc = cutoff.astimezone(UTC)
        shredded: list[str] = []
        already: list[str] = []
        for path in sorted(manifests_root.rglob("*.encrypted.manifest.json")):
            manifest = self.read_manifest(path)
            if _parse_time(str(manifest["generated_at"])) > cutoff_utc:
                continue
            if str(manifest.get("key_state")) == "SHREDDED":
                already.append(str(manifest["backup_id"]))
                continue
            self.shred_key(path, reason=reason)
            shredded.append(str(manifest["backup_id"]))
        return {"cutoff": cutoff_utc.isoformat(), "shredded": shredded, "already_shredded": already}
