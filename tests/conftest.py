from __future__ import annotations

import base64
import os
import tempfile


def pytest_configure(config):
    if os.name != "nt":
        os.environ.setdefault("MEMORY_POSIX_WRAP_KEY_B64", base64.b64encode(b"T" * 32).decode("ascii"))
        os.environ.setdefault("MEMORY_VAULT_ROOT", tempfile.mkdtemp(prefix="memoria-v52-test-vault-"))
