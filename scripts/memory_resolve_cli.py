from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\New Projet\MEMORIA-PERMANENTE")
sys.path.insert(0, str(ROOT / "src"))
from memory_permanent.signed_client import SignedMemoryClient  # noqa: E402

BASE = (os.getenv("MEMORY_API_URL") or "http://localhost:8787").rstrip("/")
CLIENT_ID = (os.getenv("MEMORY_WMCP_CLIENT_ID") or "wmcp-memory-bridge").strip()

def post_json(path: str, payload: dict) -> dict:
    status, result = SignedMemoryClient(BASE, CLIENT_ID).request("POST", path, payload, timeout=5)
    if status < 200 or status >= 300:
        raise RuntimeError(f"Memory API HTTP {status}: {json.dumps(result, ensure_ascii=False)[:1000]}")
    if not isinstance(result, dict):
        raise RuntimeError("Memory API returned a non-object response")
    return result

def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        sys.stdout.write(json.dumps({"ok": False, "error": "conversation_id_required"}) + "\n")
        return 2
    ref = sys.argv[1].strip()
    started = time.perf_counter()
    try:
        result = post_json("/v1/conversations/recover", {"provider": "chatgpt", "external_session_ref": ref})
    except (OSError, RuntimeError, ValueError) as exc:
        sys.stdout.write(json.dumps({"ok": False, "error_type": type(exc).__name__, "error": str(exc)}, ensure_ascii=False) + "\n")
        return 4
    result["lookup_ms"] = round((time.perf_counter() - started) * 1000, 3)
    result["ok"] = True
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
