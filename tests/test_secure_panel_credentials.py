from pathlib import Path


def test_operator_panel_never_embeds_long_lived_hmac_secret_in_browser():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "open_secure_panel.py").read_text(encoding="utf-8")
    js = (root / "src" / "memory_permanent" / "static" / "app.js").read_text(encoding="utf-8")
    assert "#client_id=" not in launcher
    assert "&secret=" not in launcher
    assert "memoryClientSecret" not in js
    assert "X-Memory-Signature" not in js
    assert "browser_token" in launcher
    assert "memoryBrowserToken" in js
