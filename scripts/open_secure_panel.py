from __future__ import annotations

import urllib.parse
import webbrowser

from memory_permanent.signed_client import SignedMemoryClient


def main() -> int:
    client = SignedMemoryClient("http://127.0.0.1:8787", "local-admin")
    status, payload = client.request("POST", "/v1/auth/browser-sessions", {"ttl_seconds": 600}, timeout=10)
    if status != 200 or not isinstance(payload, dict) or not payload.get("token"):
        raise RuntimeError(f"browser session bootstrap failed: HTTP {status}")
    token = urllib.parse.quote(str(payload["token"]), safe="")
    url = f"http://127.0.0.1:8787/#browser_token={token}"
    ok = webbrowser.open(url, new=2)
    print("SECURE_PANEL_LAUNCH=PASS" if ok else "SECURE_PANEL_LAUNCH=REQUESTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
