from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from memory_permanent.client_auth import (
    BrowserSessionRegistry,
    ClientRegistry,
    ReplayGuard,
)


def test_client_registry_corrupt_json_fails_closed_503(tmp_path: Path):
    (tmp_path/"clients.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        ClientRegistry(tmp_path).get("client-a")
    assert exc.value.status_code == 503


def test_client_registry_secret_path_traversal_is_rejected_before_key_access(tmp_path: Path):
    payload={
        "version":1,
        "clients":{
            "client-a":{
                "status":"ACTIVE",
                "secret_file":"../outside-secret.key",
                "permissions":["memory:read"],
                "tenants":["TENANT_A"],
            }
        },
    }
    (tmp_path/"clients.json").write_text(json.dumps(payload),encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        ClientRegistry(tmp_path).get("client-a")
    assert exc.value.status_code == 503
    assert "secret path" in exc.value.detail


def test_replay_corrupt_state_fails_closed(tmp_path: Path):
    state=tmp_path/"replay.json"
    state.write_text("{corrupt",encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        ReplayGuard(state_path=state).accept("client-a","a"*32,1000)
    assert exc.value.status_code == 503


def test_browser_corrupt_state_fails_closed(tmp_path: Path):
    state=tmp_path/"browser.json"
    state.write_text("{corrupt",encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        BrowserSessionRegistry(state_path=state).authenticate("synthetic",now=1000)
    assert exc.value.status_code == 503
