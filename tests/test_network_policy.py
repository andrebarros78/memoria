from __future__ import annotations

import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from memory_permanent.network_policy import (
    read_http_response_limited,
    validate_origin_relative_path_query,
    validate_service_base_url,
)
from memory_permanent.provider_adapter import (
    OllamaProviderAdapter,
    OpenAIProviderAdapter,
)
from memory_permanent.signed_client import SignedMemoryClient


def test_service_url_allows_https_and_loopback_http():
    assert validate_service_base_url("https://api.example.com/v1/", purpose="test") == "https://api.example.com/v1"
    assert validate_service_base_url("http://127.0.0.1:8787", purpose="test") == "http://127.0.0.1:8787"
    assert validate_service_base_url("http://localhost:11434", purpose="test") == "http://localhost:11434"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com/#frag",
        "https://example.com/?q=x",
    ],
)
def test_service_url_rejects_unsafe_transport_and_credential_forms(url):
    with pytest.raises(ValueError):
        validate_service_base_url(url, purpose="test")


def test_adapters_and_signed_client_enforce_url_policy():
    with pytest.raises(ValueError):
        OpenAIProviderAdapter(api_key="synthetic", base_url="file:///tmp")
    with pytest.raises(ValueError):
        OllamaProviderAdapter(base_url="http://remote.example")
    with pytest.raises(ValueError):
        SignedMemoryClient("http://remote.example:8787", "local-admin")
    remote = SignedMemoryClient("https://remote.example", "local-admin")
    assert remote.base_url == "https://remote.example"


def test_openai_provider_does_not_follow_redirect_or_forward_authorization():
    seen = {"target_reached": False, "authorization": None}

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["target_reached"] = True
            seen["authorization"] = self.headers.get("Authorization")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data":[]}')

        def log_message(self, format, *args):
            return

    class RedirectHandler(BaseHTTPRequestHandler):
        target_port = 0

        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.target_port}/stolen")
            self.end_headers()

        def log_message(self, format, *args):
            return

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    RedirectHandler.target_port = target.server_port
    redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (target, redirect)]
    for thread in threads:
        thread.start()
    try:
        adapter = OpenAIProviderAdapter(
            api_key="synthetic-sensitive-key",
            base_url=f"http://127.0.0.1:{redirect.server_port}",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            adapter.probe()
        assert exc.value.code == 302
        assert seen["target_reached"] is False
        assert seen["authorization"] is None
    finally:
        redirect.shutdown()
        target.shutdown()
        redirect.server_close()
        target.server_close()


def test_signed_client_does_not_follow_redirect(monkeypatch):
    seen = {"target_reached": False}

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["target_reached"] = True
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, format, *args):
            return

    class RedirectHandler(BaseHTTPRequestHandler):
        target_port = 0

        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.target_port}/redirected")
            self.end_headers()

        def log_message(self, format, *args):
            return

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    RedirectHandler.target_port = target.server_port
    redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (target, redirect)]
    for thread in threads:
        thread.start()
    try:
        monkeypatch.setattr(SignedMemoryClient, "_secret", lambda self: b"x" * 32)
        client = SignedMemoryClient(f"http://127.0.0.1:{redirect.server_port}", "synthetic-client")
        status, _ = client.request("GET", "/start")
        assert status == 302
        assert seen["target_reached"] is False
    finally:
        redirect.shutdown()
        target.shutdown()
        redirect.server_close()
        target.server_close()


class _FakeResponse:
    def __init__(self, payload: bytes, content_length: str | None = None) -> None:
        self.payload = payload
        self.headers = {} if content_length is None else {"Content-Length": content_length}

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


def test_http_response_limit_rejects_declared_and_streamed_oversize():
    with pytest.raises(ValueError, match="exceeds size limit"):
        read_http_response_limited(_FakeResponse(b"small", "100"), max_bytes=16, purpose="test")
    with pytest.raises(ValueError, match="exceeds size limit"):
        read_http_response_limited(_FakeResponse(b"x" * 17), max_bytes=16, purpose="test")


def test_origin_relative_path_query_rejects_cross_origin_forms():
    assert validate_origin_relative_path_query("/v1/memories?limit=1", purpose="test") == "/v1/memories?limit=1"
    for value in ("", "v1/memories", "//evil.example/x", "https://evil.example/x", "/v1/x#fragment"):
        with pytest.raises(ValueError):
            validate_origin_relative_path_query(value, purpose="test")


def test_signed_client_rejects_non_relative_request_paths(monkeypatch):
    monkeypatch.setattr(SignedMemoryClient, "_secret", lambda self: b"x" * 32)
    client = SignedMemoryClient("http://127.0.0.1:8787", "synthetic-client")
    for value in ("https://evil.example/x", "//evil.example/x", "v1/memories"):
        with pytest.raises(ValueError):
            client.headers("GET", value)
