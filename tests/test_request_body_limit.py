from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from memory_permanent.client_auth import read_request_body_limited


def _request(chunks: list[bytes], *, content_length: str | None = None) -> Request:
    headers = [] if content_length is None else [(b"content-length", content_length.encode())]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/memories",
        "raw_path": b"/v1/memories",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 8787),
    }
    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ] or [{"type": "http.request", "body": b"", "more_body": False}]

    async def receive():
        return messages.pop(0)

    return Request(scope, receive)


def test_request_body_limit_preserves_body_for_downstream_consumers():
    request = _request([b"abc", b"def"], content_length="6")
    body = asyncio.run(read_request_body_limited(request, max_bytes=16))
    assert body == b"abcdef"
    assert asyncio.run(request.body()) == b"abcdef"


def test_request_body_limit_rejects_declared_oversize_before_read():
    request = _request([b"x"], content_length="17")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_request_body_limited(request, max_bytes=16))
    assert exc.value.status_code == 413


def test_request_body_limit_rejects_streamed_oversize_without_content_length():
    request = _request([b"abcdefgh", b"ijklmnop", b"q"])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_request_body_limited(request, max_bytes=16))
    assert exc.value.status_code == 413


def test_request_body_limit_rejects_invalid_content_length():
    request = _request([b"x"], content_length="not-a-number")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_request_body_limited(request, max_bytes=16))
    assert exc.value.status_code == 400
