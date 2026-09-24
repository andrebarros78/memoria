import hashlib
import hmac
import os

import pytest
from fastapi import HTTPException

from memory_permanent.client_auth import (
    BrowserSessionRegistry,
    ClientPrincipal,
    ReplayGuard,
    canonical_request,
    sign_headers,
)


def principal(**overrides):
    base = dict(
        client_id="client-a",
        permissions=frozenset({"memory:general"}),
        tenants=frozenset({"TENANT_A"}),
        agents=frozenset({"agent-a"}),
        users=frozenset({"user-a"}),
        projects=frozenset({"project-a"}),
        teams=frozenset({"team-a"}),
        organizations=frozenset({"org-a"}),
        default_tenant="TENANT_A",
        default_agent="agent-a",
        default_user="user-a",
        default_project="project-a",
        default_team="team-a",
        default_organization="org-a",
    )
    base.update(overrides)
    return ClientPrincipal(**base)


def test_claims_cannot_expand_beyond_authenticated_client():
    p = principal()
    with pytest.raises(HTTPException) as exc:
        p.resolve_claims(tenant="TENANT_B", agent=None, user=None, project=None, team=None, organization=None)
    assert exc.value.status_code == 403


def test_claims_default_to_authenticated_principal():
    claims = principal().resolve_claims(tenant=None, agent=None, user=None, project=None, team=None, organization=None)
    assert claims == {
        "tenant": "TENANT_A", "agent": "agent-a", "user": "user-a",
        "project": "project-a", "team": "team-a", "organization": "org-a",
    }


def test_hmac_signature_binds_method_path_and_body():
    secret = b"a" * 32
    body = b'{"x":1}'
    headers = sign_headers(client_id="client-a", secret=secret, method="POST", path_query="/v1/memories?x=1", body=body)
    canonical = canonical_request("POST", "/v1/memories?x=1", headers["X-Memory-Timestamp"], headers["X-Memory-Nonce"], headers["X-Memory-Content-SHA256"])
    expected = hmac.new(secret, canonical, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected, headers["X-Memory-Signature"])
    assert headers["X-Memory-Content-SHA256"] == hashlib.sha256(body).hexdigest()


def test_replay_guard_rejects_same_nonce():
    guard = ReplayGuard()
    guard.accept("client-a", "a" * 32, 1000)
    with pytest.raises(HTTPException) as exc:
        guard.accept("client-a", "a" * 32, 1000)
    assert exc.value.status_code == 401


def test_replay_guard_fails_closed_instead_of_evicting_live_nonce():
    guard = ReplayGuard(max_entries=1)
    guard.accept("client-a", "a" * 32, 1000)
    with pytest.raises(HTTPException) as exc:
        guard.accept("client-a", "b" * 32, 1001)
    assert exc.value.status_code == 503


def test_durable_replay_guard_survives_restart(tmp_path):
    state = tmp_path / "replay.json"
    ReplayGuard(state_path=state).accept("client-a", "c" * 32, 1000)
    restarted = ReplayGuard(state_path=state)
    with pytest.raises(HTTPException) as exc:
        restarted.accept("client-a", "c" * 32, 1001)
    assert exc.value.status_code == 401
    if os.name != "nt":
        # POSIX privacy is represented by permission bits. Windows privacy is
        # represented by NTFS ACLs and is validated in the Windows integration gate.
        assert (state.stat().st_mode & 0o077) == 0
    assert ("c" * 32) not in state.read_text(encoding="utf-8")


def test_browser_session_is_short_lived_hashed_and_least_privilege(tmp_path):
    source = principal(permissions=frozenset({"*"}))
    state = tmp_path / "browser.json"
    registry = BrowserSessionRegistry(state_path=state)
    issued = registry.issue(source, 120, now=1000)
    token = issued["token"]
    assert token not in state.read_text(encoding="utf-8")
    browser = registry.authenticate(token, now=1001)
    assert browser.permissions == frozenset({"memory:read", "memory:admin"})
    assert browser.allows_permission("memory:purge") is False
    assert browser.allows_permission("memory:browser-session") is False
    with pytest.raises(HTTPException) as exc:
        registry.authenticate(token, now=1121)
    assert exc.value.status_code == 401


def test_browser_session_capacity_fails_closed(tmp_path):
    registry = BrowserSessionRegistry(state_path=tmp_path / "browser.json", max_sessions=1)
    registry.issue(principal(permissions=frozenset({"*"})), 120, now=1000)
    with pytest.raises(HTTPException) as exc:
        registry.issue(principal(permissions=frozenset({"*"})), 120, now=1001)
    assert exc.value.status_code == 503

def test_browser_bearer_cannot_mutate_even_with_admin_permission(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import memory_permanent.client_auth as auth

    browser = principal(permissions=frozenset({"memory:read", "memory:admin"}))
    monkeypatch.setattr(auth._browser_sessions, "authenticate", lambda token: browser)

    class Headers(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    request = SimpleNamespace(
        headers=Headers({"Authorization": "Bearer synthetic-browser-token"}),
        method="POST",
        url=SimpleNamespace(path="/v1/memories/classify", query=""),
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.authenticate_request(request))
    assert exc.value.status_code == 403
    assert exc.value.detail == "browser session mutation is not allowed"


def test_browser_bearer_can_read_admin_dashboard(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import memory_permanent.client_auth as auth

    browser = principal(permissions=frozenset({"memory:read", "memory:admin"}))
    monkeypatch.setattr(auth._browser_sessions, "authenticate", lambda token: browser)

    class Headers(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    request = SimpleNamespace(
        headers=Headers({"Authorization": "Bearer synthetic-browser-token"}),
        method="GET",
        url=SimpleNamespace(path="/v1/dashboard/summary", query=""),
    )
    resolved = asyncio.run(auth.authenticate_request(request))
    assert resolved is browser
