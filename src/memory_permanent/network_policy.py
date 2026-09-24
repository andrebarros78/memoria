from __future__ import annotations

import ipaddress
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

PROVIDER_RESPONSE_MAX_BYTES = 8 * 1024 * 1024
MEMORY_API_RESPONSE_MAX_BYTES = 64 * 1024 * 1024
HTTP_ERROR_RESPONSE_MAX_BYTES = 1024 * 1024


class _DenyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Fail closed on HTTP redirects so credentials cannot cross origins."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            "redirect blocked by network policy",
            headers,
            fp,
        )


_NO_REDIRECT_OPENER = urllib.request.build_opener(_DenyRedirectHandler())


def _is_loopback(hostname: str) -> bool:
    host = hostname.strip().lower().rstrip(".")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_service_base_url(value: str, *, purpose: str) -> str:
    base = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(base)
    except ValueError as exc:
        raise ValueError(f"{purpose} base URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{purpose} base URL must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{purpose} base URL must not embed credentials")
    if parsed.query or parsed.fragment:
        raise ValueError(f"{purpose} base URL must not contain query or fragment")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        raise ValueError(f"{purpose} cleartext HTTP is restricted to loopback")
    return base


def validate_loopback_service_base_url(value: str, *, purpose: str) -> str:
    base = validate_service_base_url(value, purpose=purpose)
    parsed = urlsplit(base)
    if not parsed.hostname or not _is_loopback(parsed.hostname):
        raise ValueError(f"{purpose} base URL must remain loopback-local")
    return base


def validate_origin_relative_path_query(value: str, *, purpose: str) -> str:
    path_query = str(value or "").strip()
    if not path_query.startswith("/") or path_query.startswith("//"):
        raise ValueError(f"{purpose} path must be origin-relative")
    try:
        parsed = urlsplit(path_query)
    except ValueError as exc:
        raise ValueError(f"{purpose} path is invalid") from exc
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError(f"{purpose} path must not change origin or contain fragment")
    return path_query


def open_url_no_redirect(request: urllib.request.Request, *, timeout: float) -> Any:
    """Open one validated request without following HTTP redirects."""

    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)


def read_http_response_limited(response: Any, *, max_bytes: int, purpose: str) -> bytes:
    """Read at most max_bytes and fail closed on oversized HTTP responses."""

    if max_bytes <= 0:
        raise ValueError("HTTP response size limit must be positive")
    content_length = None
    headers = getattr(response, "headers", None)
    if headers is not None:
        raw_length = headers.get("Content-Length")
        if raw_length:
            try:
                content_length = int(raw_length)
            except (TypeError, ValueError):
                content_length = None
    if content_length is not None and content_length > max_bytes:
        raise ValueError(f"{purpose} response exceeds size limit")
    payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError(f"{purpose} response exceeds size limit")
    return payload
