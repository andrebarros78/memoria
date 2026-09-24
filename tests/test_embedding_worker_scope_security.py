from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from memory_permanent.embedding_provider import FastEmbedProvider

ROOT = Path(__file__).resolve().parents[1]


class _FakeTextEmbedding:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def embed(self, texts):
        for _ in texts:
            yield [0.0, 1.0, 2.0]


def _install_fake_fastembed(monkeypatch):
    fake = types.SimpleNamespace(TextEmbedding=_FakeTextEmbedding)
    monkeypatch.setitem(sys.modules, "fastembed", fake)


def _worker_module():
    path = ROOT / "scripts" / "embedding_worker.py"
    spec = importlib.util.spec_from_file_location("canonical_embedding_worker_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_embedding_provider_identity_is_versionable(monkeypatch):
    _install_fake_fastembed(monkeypatch)
    provider = FastEmbedProvider(model_name="model-a", identity="model-a|engine-1|pool-v2")
    assert provider.model_id == "model-a|engine-1|pool-v2"
    assert provider.dimensions == 3


def test_embedding_provider_identity_defaults_to_model_name(monkeypatch):
    _install_fake_fastembed(monkeypatch)
    provider = FastEmbedProvider(model_name="model-a")
    assert provider.model_id == "model-a"


def test_embedding_scope_discovery_is_dedicated_role_only():
    sql = (ROOT / "migrations" / "0053_embedding_worker_scope_discovery.sql").read_text(encoding="utf-8")
    assert "CREATE ROLE memory_embedding_worker" in sql
    assert "NOBYPASSRLS" in sql
    assert "session_user <> 'memory_embedding_worker'" in sql
    assert "REVOKE ALL ON FUNCTION public.memory_embedding_access_contexts(text,integer) FROM memory_app" in sql
    assert "REVOKE ALL ON FUNCTION public.memory_embedding_access_contexts(text,integer) FROM memory_admin" in sql
    assert "GRANT EXECUTE ON FUNCTION public.memory_embedding_access_contexts(text,integer) TO memory_embedding_worker" in sql
    assert "GRANT SELECT ON" not in sql


def test_worker_maps_project_context_without_system_bypass():
    worker = _worker_module()
    access = worker._access_context(
        {
            "sharing_scope": "PROJECT_SHARED",
            "project_id": "project-a",
            "owner_user_id": None,
            "owner_agent_id": None,
            "team_id": None,
            "organization_id": None,
        }
    )
    assert access.project_id == "project-a"
    assert access.agent_id == "embedding-worker"
    assert access.agent_id != "__SYSTEM__"


def test_worker_maps_private_agent_to_owner_context():
    worker = _worker_module()
    access = worker._access_context(
        {
            "sharing_scope": "AGENT_PRIVATE",
            "owner_agent_id": "agent-owner",
            "owner_user_id": None,
            "project_id": None,
            "team_id": None,
            "organization_id": None,
        }
    )
    assert access.agent_id == "agent-owner"
    assert access.agent_id != "__SYSTEM__"
