from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import re
from ctypes import wintypes
from pathlib import Path
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultKeyProvider(Protocol):
    def load_or_create(self) -> bytes: ...
    def protect_existing(self, key: bytes) -> None: ...


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob_from_bytes(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _dpapi_protect(data: bytes, *, machine_scope: bool = True, entropy: bytes = b"MEMORIA-PERMANENTE:VAULT:V1") -> bytes:
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI is only available on Windows")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, keepalive = _blob_from_bytes(data)
    entropy_blob, entropy_keepalive = _blob_from_bytes(entropy)
    out_blob = _DATA_BLOB()
    flags = 0x4 if machine_scope else 0  # CRYPTPROTECT_LOCAL_MACHINE
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "MEMORIA-PERMANENTE vault key",
        ctypes.byref(entropy_blob),
        None,
        None,
        flags,
        ctypes.byref(out_blob),
    )
    _ = keepalive, entropy_keepalive
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(data: bytes, *, entropy: bytes = b"MEMORIA-PERMANENTE:VAULT:V1") -> bytes:
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI is only available on Windows")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob, keepalive = _blob_from_bytes(data)
    entropy_blob, entropy_keepalive = _blob_from_bytes(entropy)
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    _ = keepalive, entropy_keepalive
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


class WindowsDpapiKeyProvider:
    """AES key material protected by DPAPI and stored outside the product tree."""

    provider_name = "WINDOWS_DPAPI_MACHINE"

    def __init__(self, key_path: Path, *, machine_scope: bool = True, entropy: bytes = b"MEMORIA-PERMANENTE:VAULT:V1") -> None:
        self.key_path = Path(key_path)
        self.machine_scope = machine_scope
        self.entropy = bytes(entropy)

    def protect_existing(self, key: bytes) -> None:
        if len(key) != 32:
            raise RuntimeError("invalid vault key length")
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        protected = _dpapi_protect(key, machine_scope=self.machine_scope, entropy=self.entropy)
        tmp = self.key_path.with_suffix(self.key_path.suffix + ".tmp")
        tmp.write_bytes(protected)
        os.replace(tmp, self.key_path)

    def load_or_create(self) -> bytes:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            self.protect_existing(AESGCM.generate_key(bit_length=256))
        key = _dpapi_unprotect(self.key_path.read_bytes(), entropy=self.entropy)
        if len(key) != 32:
            raise RuntimeError("invalid DPAPI vault key")
        return key


class PosixAesWrappedKeyProvider:
    """Protect local key material with an externally supplied POSIX wrapping key.

    The wrapping key must come from MEMORY_POSIX_WRAP_KEY_FILE (preferred) or
    MEMORY_POSIX_WRAP_KEY_B64. It is never generated or persisted by this
    provider, so Linux production fails closed when no external secret is
    provisioned. Individual service keys remain encrypted at rest.
    """

    provider_name = "POSIX_AES256_GCM_WRAPPED"

    def __init__(self, key_path: Path, *, entropy: bytes = b"MEMORIA-PERMANENTE:VAULT:V1") -> None:
        self.key_path = Path(key_path)
        self.entropy = bytes(entropy)

    @staticmethod
    def _decode_key_material(raw: bytes, *, source: str) -> bytes:
        if len(raw) == 32:
            return raw
        text = raw.strip()
        try:
            decoded = base64.b64decode(text, validate=True)
        except Exception as exc:
            raise RuntimeError(f"invalid POSIX wrapping key encoding from {source}") from exc
        if len(decoded) != 32:
            raise RuntimeError(f"POSIX wrapping key from {source} must decode to exactly 32 bytes")
        return decoded

    @classmethod
    def _load_wrapping_key(cls) -> bytes:
        file_value = os.getenv("MEMORY_POSIX_WRAP_KEY_FILE", "").strip()
        if file_value:
            path = Path(file_value)
            try:
                mode = path.stat().st_mode
            except FileNotFoundError as exc:
                raise RuntimeError("MEMORY_POSIX_WRAP_KEY_FILE does not exist") from exc
            if mode & 0o077:
                raise RuntimeError("MEMORY_POSIX_WRAP_KEY_FILE must not be accessible by group/other")
            return cls._decode_key_material(path.read_bytes(), source="MEMORY_POSIX_WRAP_KEY_FILE")
        value = os.getenv("MEMORY_POSIX_WRAP_KEY_B64", "").strip()
        if value:
            return cls._decode_key_material(value.encode("ascii"), source="MEMORY_POSIX_WRAP_KEY_B64")
        raise RuntimeError(
            "POSIX key protection requires MEMORY_POSIX_WRAP_KEY_FILE or MEMORY_POSIX_WRAP_KEY_B64"
        )

    def _aad(self) -> bytes:
        return b"MEMORIA-PERMANENTE:POSIX-WRAP:V1\0" + self.entropy

    def protect_existing(self, key: bytes) -> None:
        if len(key) != 32:
            raise RuntimeError("invalid vault key length")
        wrapping_key = self._load_wrapping_key()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.key_path.parent, 0o700)
        except OSError:
            pass
        nonce = os.urandom(12)
        ciphertext = AESGCM(wrapping_key).encrypt(nonce, key, self._aad())
        payload = {
            "version": 1,
            "provider": self.provider_name,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        tmp = self.key_path.with_suffix(self.key_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.key_path)
        os.chmod(self.key_path, 0o600)

    def load_or_create(self) -> bytes:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            self.protect_existing(AESGCM.generate_key(bit_length=256))
        try:
            payload = json.loads(self.key_path.read_text(encoding="utf-8"))
            if int(payload.get("version", 0)) != 1 or payload.get("provider") != self.provider_name:
                raise RuntimeError("invalid POSIX wrapped key envelope")
            nonce = base64.b64decode(payload["nonce"], validate=True)
            ciphertext = base64.b64decode(payload["ciphertext"], validate=True)
            key = AESGCM(self._load_wrapping_key()).decrypt(nonce, ciphertext, self._aad())
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("invalid POSIX wrapped key envelope") from exc
        if len(key) != 32:
            raise RuntimeError("invalid POSIX unwrapped key length")
        return key


def platform_key_provider(
    key_path: Path, *, machine_scope: bool = True, entropy: bytes = b"MEMORIA-PERMANENTE:VAULT:V1"
) -> VaultKeyProvider:
    if os.name == "nt":
        return WindowsDpapiKeyProvider(key_path, machine_scope=machine_scope, entropy=entropy)
    return PosixAesWrappedKeyProvider(key_path, entropy=entropy)


def platform_protected_key_path(root: Path, stem: str, *, platform_name: str | None = None) -> Path:
    """Return a stable key path without breaking historical Windows DPAPI names."""
    name = str(stem or "").strip()
    if not name or any(ch in name for ch in ("/", "\\")):
        raise ValueError("invalid protected key stem")
    platform = os.name if platform_name is None else str(platform_name)
    suffix = ".dpapi" if platform == "nt" else ".key"
    return Path(root) / f"{name}{suffix}"


def platform_key_reference(namespace: str, key_id: str, *, platform_name: str | None = None) -> str:
    platform = os.name if platform_name is None else str(platform_name)
    scheme = "dpapi" if platform == "nt" else "posix-wrapped"
    return f"{scheme}://{str(namespace).strip('/')}/{key_id!s}"


def default_vault_root() -> Path:
    configured = os.getenv("MEMORY_VAULT_ROOT", "").strip()
    if configured:
        return Path(configured)
    if os.name == "nt":
        program_data = os.getenv("ProgramData", r"C:\ProgramData")
        return Path(program_data) / "MemoriaPermanente" / "vault"
    return Path("/var/lib/memoria-permanente/vault")


class LocalEncryptedVault:
    """Local AES-GCM vault with platform-specific protection for the master key."""

    def __init__(self, root: Path | None = None, key_provider: VaultKeyProvider | None = None) -> None:
        self.root = Path(root) if root is not None else default_vault_root()
        self.root.mkdir(parents=True, exist_ok=True)
        provider = key_provider or platform_key_provider(platform_protected_key_path(self.root, "vault-master"), machine_scope=True)
        self.key_provider = provider
        self.key = provider.load_or_create()
        if len(self.key) != 32:
            raise RuntimeError("invalid vault key")

    @classmethod
    def from_environment(cls) -> LocalEncryptedVault:
        return cls(default_vault_root())

    def put(self, *, tenant_id: str, secret: str, kind: str) -> str:
        if not secret:
            raise ValueError("empty secret")
        digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        ref = f"vault://memory/{tenant_id.lower()}/{digest[:24]}"
        path = self.root / f"{tenant_id.lower()}-{digest[:24]}.json"
        if not path.exists():
            nonce = os.urandom(12)
            aad = f"{tenant_id}:{kind}:{ref}".encode()
            ciphertext = AESGCM(self.key).encrypt(nonce, secret.encode("utf-8"), aad)
            payload = {
                "version": 2,
                "key_provider": getattr(self.key_provider, "provider_name", type(self.key_provider).__name__),
                "tenant_id": tenant_id,
                "kind": kind,
                "ref": ref,
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            }
            path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return ref

    def get(self, ref: str) -> str:
        match = re.fullmatch(r"vault://memory/([a-z0-9_.:-]+)/([0-9a-f]{24})", ref)
        if not match:
            raise ValueError("invalid secret_ref")
        tenant, short = match.groups()
        path = self.root / f"{tenant}-{short}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        nonce = base64.b64decode(payload["nonce"])
        ciphertext = base64.b64decode(payload["ciphertext"])
        aad = f"{payload['tenant_id']}:{payload['kind']}:{payload['ref']}".encode()
        return AESGCM(self.key).decrypt(nonce, ciphertext, aad).decode("utf-8")


class SecretSanitizer:
    _patterns = (
        ("authorization_bearer", re.compile(r"(?i)((?:authorization|proxy[-_ ]authorization)\s*:\s*Bearer\s+)([^\s,;]+)")),
        ("openai_key", re.compile(r"\b(sk-[A-Za-z0-9_-]{16,})\b")),
        ("github_token", re.compile(r"\b(gh[oprsu]_[A-Za-z0-9]{30,})\b")),
        ("slack_token", re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{20,})\b")),
        ("google_api_key", re.compile(r"\b(AIza[0-9A-Za-z_-]{35})\b")),
        ("stripe_secret", re.compile(r"\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,})\b")),
        ("jwt", re.compile(r"\b(eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{16,})\b")),
        ("aws_access_key", re.compile(r"\b((?:AKIA|ASIA)[A-Z0-9]{16})\b")),
        ("database_password", re.compile(r"(?i)((?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|amqp)://[^:/@\s]+:)([^@/\s]+)(@)")),
        ("password", re.compile(r"(?i)\b((?:password|senha|passwd)\s*[:=]\s*)([^\s,;]+)")),
        (
            "credential_field",
            re.compile(
                r"(?i)\b((?:x[-_ ]api[-_ ]key|x[-_ ]auth[-_ ]token|api[-_ ]key|access[-_ ]token|refresh[-_ ]token|id[-_ ]token|auth[-_ ]token|bearer[-_ ]token|client[-_ ]secret|aws[-_ ]secret[-_ ]access[-_ ]key|secret[-_ ]access[-_ ]key|webhook[-_ ]secret|signing[-_ ]secret|private[-_ ]key)\s*[:=]\s*)([^\s,;]+)"
            ),
        ),
        ("cookie", re.compile(r"(?i)\b((?:cookie|set[-_ ]cookie|session[-_ ]id)\s*[:=]\s*)([^\r\n;]+)")),
    )
    _pem_private_key = re.compile(
        r"-----BEGIN (?P<kind>(?:(?:RSA|EC|DSA|OPENSSH) )?PRIVATE KEY)-----.*?-----END (?P=kind)-----",
        re.DOTALL,
    )
    _sensitive_exact = frozenset(
        {
            "password", "senha", "passwd", "api_key", "apikey", "x_api_key",
            "access_token", "refresh_token", "id_token", "auth_token", "x_auth_token",
            "bearer_token", "authorization", "proxy_authorization", "cookie", "set_cookie",
            "session_id", "sessionid", "client_secret", "private_key", "secret",
            "secret_access_key", "aws_secret_access_key", "webhook_secret", "signing_secret",
            "signing_key", "credential", "credentials", "token", "secret_key",
            "github_token", "database_url",
        }
    )
    _sensitive_suffixes = (
        "_password", "_passwd", "_api_key", "_access_token", "_refresh_token", "_id_token",
        "_auth_token", "_bearer_token", "_client_secret", "_private_key", "_secret_access_key",
        "_webhook_secret", "_signing_secret", "_credential", "_credentials",
        "_token", "_secret", "_secret_key", "_database_url",
    )

    def __init__(self, vault: LocalEncryptedVault, tenant_id: str) -> None:
        self.vault = vault
        self.tenant_id = tenant_id
        self.refs: list[str] = []

    @staticmethod
    def _normalize_key(key: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower())
        return re.sub(r"_+", "_", normalized).strip("_")

    @classmethod
    def _is_sensitive_key(cls, key: str) -> bool:
        normalized = cls._normalize_key(key)
        return normalized in cls._sensitive_exact or any(normalized.endswith(suffix) for suffix in cls._sensitive_suffixes)

    def _vault_secret(self, secret: str, kind: str) -> str:
        ref = self.vault.put(tenant_id=self.tenant_id, secret=secret, kind=kind)
        self.refs.append(ref)
        return ref

    def _replace_text(self, text: str) -> str:
        result = text
        for kind, pattern in self._patterns:
            def repl(match: re.Match[str], *, kind: str = kind) -> str:
                groups = match.groups()
                secret = groups[1] if kind == "database_password" and len(groups) == 3 else groups[-1]
                ref = self._vault_secret(secret, kind)
                if kind == "database_password" and len(groups) == 3:
                    return groups[0] + ref + groups[2]
                if len(groups) >= 2:
                    return groups[0] + ref
                return ref
            result = pattern.sub(repl, result)

        def pem_repl(match: re.Match[str]) -> str:
            return self._vault_secret(match.group(0), "private_key")

        return self._pem_private_key.sub(pem_repl, result)

    def _sanitize_keyed_value(self, key: str, value: Any) -> Any:
        if self._is_sensitive_key(key) and isinstance(value, str) and value and not value.startswith("vault://"):
            return self._vault_secret(value, f"field:{self._normalize_key(key)}")
        return self.sanitize(value)

    def sanitize(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._replace_text(value)
        if isinstance(value, dict):
            return {str(k): self._sanitize_keyed_value(str(k), v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.sanitize(v) for v in value]
        if isinstance(value, tuple):
            return [self.sanitize(v) for v in value]
        return value

    def sanitize_memory(self, *, content: dict[str, Any], content_text: str) -> tuple[dict[str, Any], str, list[str]]:
        self.refs = []
        clean_content = self.sanitize(content)
        clean_text = self.sanitize(content_text)
        return clean_content, clean_text, sorted(set(self.refs))
