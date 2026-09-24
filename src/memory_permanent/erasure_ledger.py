from __future__ import annotations

import hashlib
import hmac
import json
import os

try:
    import msvcrt  # type: ignore[import-not-found]
except ImportError:  # POSIX/Linux
    msvcrt = None  # type: ignore[assignment]
    import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .secret_sanitizer import platform_key_provider, platform_protected_key_path

EXTERNAL_ERASURE_LEDGER_VERSION = "EL-1.0.0"
LEDGER_KEY_ENTROPY = b"MEMORIA-PERMANENTE:ERASURE-LEDGER:EL1"
ZERO_HMAC = "0" * 64


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def safe_reason_code(value: str) -> str:
    code = str(value or "").strip().upper()
    if not code or len(code) > 64 or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in code):
        raise ValueError("reason_code must be a non-sensitive policy code")
    return code


def default_erasure_root() -> Path:
    configured = os.getenv("MEMORY_ERASURE_ROOT", "").strip()
    if configured:
        return Path(configured)
    if os.name == "nt":
        return Path(os.getenv("ProgramData", r"C:\ProgramData")) / "MemoriaPermanente" / "erasure"
    return Path("/var/lib/memoria-permanente/erasure")


class ExternalErasureLedger:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else default_erasure_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.root / "ledger.jsonl"
        self.lock_path = self.root / "ledger.lock"
        self.key = platform_key_provider(
            platform_protected_key_path(self.root, "ledger-master"), machine_scope=True, entropy=LEDGER_KEY_ENTROPY
        ).load_or_create()

    def target_token(self, tenant_id: str, item_id: str) -> str:
        material = b"TARGET\0" + str(tenant_id).upper().encode("utf-8") + b"\0" + str(item_id).encode("utf-8")
        return hmac.new(self.key, material, hashlib.sha256).hexdigest()

    def request_token(self, lifecycle_request_id: str) -> str:
        return hmac.new(self.key, b"REQUEST\0" + str(lifecycle_request_id).encode("utf-8"), hashlib.sha256).hexdigest()

    def blind_content_hash(self, content_sha256: str) -> str:
        raw = str(content_sha256).lower().strip()
        if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw):
            raise ValueError("invalid content sha256")
        return hmac.new(self.key, b"CONTENT-HASH\0" + raw.encode("ascii"), hashlib.sha256).hexdigest()

    def _entry_hmac(self, entry: dict[str, Any]) -> str:
        body = dict(entry)
        body.pop("entry_hmac", None)
        return hmac.new(self.key, canonical(body), hashlib.sha256).hexdigest()

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.lock_path.touch(exist_ok=True)
        with self.lock_path.open("r+b") as fh:
            if self.lock_path.stat().st_size == 0:
                fh.write(b"0")
                fh.flush()
            fh.seek(0)
            if msvcrt is not None:
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fh.seek(0)
                if msvcrt is not None:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for no, line in enumerate(self.ledger_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"erasure ledger JSON corruption at line {no}") from exc
        return rows
    def verify(self) -> dict[str, Any]:
        with self._lock():
            rows = self._read_unlocked()
        previous = ZERO_HMAC
        for expected_seq, entry in enumerate(rows, start=1):
            if int(entry.get("seq", 0)) != expected_seq:
                raise RuntimeError(f"erasure ledger sequence mismatch at {expected_seq}")
            if str(entry.get("previous_hmac")) != previous:
                raise RuntimeError(f"erasure ledger parent mismatch at {expected_seq}")
            actual = self._entry_hmac(entry)
            if not hmac.compare_digest(str(entry.get("entry_hmac") or ""), actual):
                raise RuntimeError(f"erasure ledger HMAC mismatch at {expected_seq}")
            previous = actual
        return {"ok": True, "entries": len(rows), "head_hmac": previous}

    def entries(self) -> list[dict[str, Any]]:
        self.verify()
        with self._lock():
            return self._read_unlocked()

    def append(
        self, *, tenant_id: str, item_id: str, lifecycle_request_id: str, content_sha256: str,
        erasure_id: str, reason_code: str, backup_cutoff_at: datetime,
    ) -> dict[str, Any]:
        tenant = str(tenant_id).upper().strip()
        target = self.target_token(tenant, item_id)
        request = self.request_token(lifecycle_request_id)
        blinded = self.blind_content_hash(content_sha256)
        cutoff = backup_cutoff_at.astimezone(UTC)
        with self._lock():
            rows = self._read_unlocked()
            previous = ZERO_HMAC
            for expected_seq, row in enumerate(rows, start=1):
                if int(row.get("seq", 0)) != expected_seq or str(row.get("previous_hmac")) != previous:
                    raise RuntimeError("erasure ledger chain invalid before append")
                actual = self._entry_hmac(row)
                if not hmac.compare_digest(str(row.get("entry_hmac") or ""), actual):
                    raise RuntimeError("erasure ledger HMAC invalid before append")
                previous = actual
                if str(row.get("request_token")) == request:
                    return dict(row)
            entry: dict[str, Any] = {
                "version": EXTERNAL_ERASURE_LEDGER_VERSION,
                "seq": len(rows) + 1,
                "erasure_id": str(erasure_id),
                "target_token": target,
                "request_token": request,
                "blinded_content_fingerprint": blinded,
                "reason_code": safe_reason_code(reason_code),
                "backup_cutoff_at": cutoff.isoformat(),
                "created_at": datetime.now(UTC).isoformat(),
                "previous_hmac": previous,
            }
            entry["entry_hmac"] = self._entry_hmac(entry)
            serialized = canonical(entry).decode("utf-8")
            forbidden = [str(item_id), str(lifecycle_request_id), str(content_sha256).lower()]
            if any(value and value in serialized for value in forbidden):
                raise RuntimeError("raw erasure identifier leaked into external ledger")
            with self.ledger_path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(serialized + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return dict(entry)

    def find_by_request(self, lifecycle_request_id: str) -> dict[str, Any] | None:
        token = self.request_token(lifecycle_request_id)
        for entry in self.entries():
            if hmac.compare_digest(str(entry.get("request_token") or ""), token):
                return dict(entry)
        return None
