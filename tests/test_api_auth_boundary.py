from __future__ import annotations

from fastapi.testclient import TestClient

import memory_permanent.client_auth as auth
from memory_permanent.api import app
from memory_permanent.client_auth import ClientPrincipal


def _browser_admin() -> ClientPrincipal:
    return ClientPrincipal(
        client_id="browser:test-admin",
        permissions=frozenset({"memory:read", "memory:admin"}),
        tenants=frozenset({"TENANT_A"}), agents=frozenset(), users=frozenset(),
        projects=frozenset(), teams=frozenset(), organizations=frozenset(),
        default_tenant="TENANT_A",
    )


def test_protected_http_route_rejects_unsigned_request_before_database_access():
    with TestClient(app) as client:
        response = client.get("/v1/memories")
    assert response.status_code == 401
    assert response.json()["detail"] == "signed Memory API client authentication required"
    assert response.headers.get("x-wmcp-product-id")


def test_browser_bearer_cannot_reach_mutating_admin_route(monkeypatch):
    monkeypatch.setattr(auth._browser_sessions, "authenticate", lambda token: _browser_admin())
    with TestClient(app) as client:
        response = client.post(
            "/v1/memories/classify",
            headers={"Authorization": "Bearer synthetic-browser-token"},
            json={"item_ids": ["mem-x"], "operator_class": "ATIVA"},
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "browser session mutation is not allowed"


def test_browser_session_bootstrap_itself_cannot_use_bearer(monkeypatch):
    monkeypatch.setattr(auth._browser_sessions, "authenticate", lambda token: _browser_admin())
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/browser-sessions",
            headers={"Authorization": "Bearer synthetic-browser-token"},
            json={"ttl_seconds": 120},
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "browser session mutation is not allowed"


def test_public_health_still_works_without_credentials():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers.get("x-wmcp-product-id")
