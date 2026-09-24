from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "integration" / "chatgpt_invisible_capture.py"


def test_capture_bridge_uses_signed_loopback_memory_client():
    text = SOURCE.read_text(encoding="utf-8")
    assert "SignedMemoryClient" in text
    assert 'memory_client_id: str = "chatgpt-capture"' in text
    assert '"/v1/external-sessions/capture"' in text
    assert "urllib.request.urlopen" not in text
    assert "_post_json(" not in text


def test_capture_browser_boundary_is_explicit():
    text = SOURCE.read_text(encoding="utf-8")
    assert "ChatGPT capture browser must target chatgpt.com or loopback test infrastructure" in text
    assert "ChatGPT capture target must remain on the configured browser origin" in text
    assert "allow_mutation=False" in text


def test_capture_reference_parser_rejects_foreign_origins_and_ambiguous_ids():
    import importlib.util

    import pytest

    spec = importlib.util.spec_from_file_location("chatgpt_invisible_capture_security_test", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parsed = module.parse_chatgpt_ref("https://chatgpt.com/g/g-p-project_1/c/conversation-1")
    assert parsed["project_id"] == "project_1"
    assert parsed["conversation_id"] == "conversation-1"
    for value in (
        "https://evil.example/g/g-p-project/c/conversation",
        "http://chatgpt.com/g/g-p-project/c/conversation",
        "https://chatgpt.com/g/g-p-project/c/conversation?x=1",
        "g/g-p-bad%0d%0aheader/c/conversation",
    ):
        with pytest.raises(ValueError):
            module.parse_chatgpt_ref(value)


def test_capture_target_requires_exact_origin():
    import importlib.util

    import pytest

    spec = importlib.util.spec_from_file_location("chatgpt_invisible_capture_origin_test", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._capture_target("http://127.0.0.1:8000", "/fixture") == "/fixture"
    assert module._capture_target("http://127.0.0.1:8000", "http://127.0.0.1:8000/fixture").endswith("/fixture")
    for value in (
        "http://127.0.0.1:8001/fixture",
        "https://127.0.0.1:8000/fixture",
        "//127.0.0.1:8001/fixture",
    ):
        with pytest.raises(ValueError):
            module._capture_target("http://127.0.0.1:8000", value)
    with pytest.raises(ValueError):
        module._capture_browser_base_url("https://chatgpt.com:444/")
