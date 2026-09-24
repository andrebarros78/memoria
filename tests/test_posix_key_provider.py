from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from memory_permanent.secret_sanitizer import PosixAesWrappedKeyProvider


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only provider")
def test_posix_provider_fails_closed_without_external_wrap_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MEMORY_POSIX_WRAP_KEY_FILE", raising=False)
    monkeypatch.delenv("MEMORY_POSIX_WRAP_KEY_B64", raising=False)
    provider = PosixAesWrappedKeyProvider(tmp_path / "key.wrap")
    with pytest.raises(RuntimeError, match="requires MEMORY_POSIX_WRAP_KEY"):
        provider.load_or_create()


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only provider")
def test_posix_provider_wraps_key_and_uses_owner_only_file(tmp_path: Path, monkeypatch):
    root = b"R" * 32
    monkeypatch.setenv("MEMORY_POSIX_WRAP_KEY_B64", base64.b64encode(root).decode("ascii"))
    provider = PosixAesWrappedKeyProvider(tmp_path / "key.wrap", entropy=b"test-context")
    key = b"K" * 32
    provider.protect_existing(key)
    raw = provider.key_path.read_bytes()
    assert key not in raw
    assert provider.load_or_create() == key
    assert provider.key_path.stat().st_mode & 0o077 == 0
