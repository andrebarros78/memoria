from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .client_auth import (
    CLIENT_AUTH_ENTROPY,
    auth_root,
    sign_headers,
    validate_client_id,
)
from .network_policy import (
    HTTP_ERROR_RESPONSE_MAX_BYTES,
    MEMORY_API_RESPONSE_MAX_BYTES,
    open_url_no_redirect,
    read_http_response_limited,
    validate_origin_relative_path_query,
    validate_service_base_url,
)
from .secret_sanitizer import platform_key_provider, platform_protected_key_path


@dataclass(slots=True)
class SignedMemoryClient:
    base_url: str
    client_id: str

    def __post_init__(self) -> None:
        self.base_url = validate_service_base_url(self.base_url, purpose="Memory API")
        self.client_id = validate_client_id(self.client_id)

    def _secret(self) -> bytes:
        return platform_key_provider(
            platform_protected_key_path(auth_root() / "clients", self.client_id),
            machine_scope=True,
            entropy=CLIENT_AUTH_ENTROPY,
        ).load_or_create()

    def headers(
        self,
        method: str,
        path_query: str,
        body: bytes = b"",
        extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        path_query = validate_origin_relative_path_query(path_query, purpose="Memory API")
        headers = sign_headers(
            client_id=self.client_id,
            secret=self._secret(),
            method=method,
            path_query=path_query,
            body=body,
        )
        if extra:
            headers.update(extra)
        return headers

    def request(
        self,
        method: str,
        path_query: str,
        payload: Any | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> tuple[int, Any]:
        path_query = validate_origin_relative_path_query(path_query, purpose="Memory API")
        body = b"" if payload is None else json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        headers = self.headers(method, path_query, body, extra_headers)
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.base_url.rstrip("/") + path_query,
            data=(body if payload is not None else None),
            method=method.upper(),
            headers=headers,
        )
        try:
            with open_url_no_redirect(req, timeout=timeout) as response:
                raw = read_http_response_limited(
                    response,
                    max_bytes=MEMORY_API_RESPONSE_MAX_BYTES,
                    purpose="Memory API",
                )
                text = raw.decode("utf-8") if raw else ""
                try:
                    parsed = json.loads(text) if text else {}
                except json.JSONDecodeError:
                    parsed = text
                return response.status, parsed
        except urllib.error.HTTPError as exc:
            error_text = read_http_response_limited(
                exc,
                max_bytes=HTTP_ERROR_RESPONSE_MAX_BYTES,
                purpose="Memory API error",
            ).decode("utf-8", errors="replace")
            try:
                parsed = json.loads(error_text) if error_text else {}
            except json.JSONDecodeError:
                parsed = error_text
            return exc.code, parsed
