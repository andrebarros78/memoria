import pytest
from fastapi import HTTPException

from memory_permanent.api import health, panel, purge_disabled


def test_health_is_available_without_database():
    body = health()
    assert body['status'] == 'ok'
    assert body['service'] == 'MEMORIA-PERMANENTE'
    assert body['purge_direct_enabled'] is False
    assert body['product_id'] == 'memoria-permanente'
    assert body['trust_class'] == 'FIRST_PARTY_SOVEREIGN'
    assert len(body['dna_sha256']) == 64


def test_panel_html_is_packaged():
    response = panel()
    text = response.body.decode('utf-8')
    assert response.status_code == 200
    assert 'Painel Operacional' in text
    assert 'Relat' in text and '.MD' in text
    assert 'DELETE_ELIGIBLE' in text


def test_direct_purge_is_explicitly_forbidden():
    with pytest.raises(HTTPException) as error:
        purge_disabled()
    assert error.value.status_code == 405
    assert 'Purge direto' in str(error.value.detail) and 'M12' in str(error.value.detail)



def test_health_allows_optional_agent_plane_to_be_absent(monkeypatch):
    import memory_permanent.api as api_module
    from memory_permanent.agent_skill_plane import RegistryError

    class MissingAgentPlane:
        def __init__(self):
            raise RegistryError("MEMORIA-PERMANENTE project root with .agents was not found")

    monkeypatch.setattr(api_module, "AgentSkillPlane", MissingAgentPlane)
    monkeypatch.delenv("MEMORY_REQUIRE_AGENT_SKILL_PLANE", raising=False)
    body = api_module.health()
    assert body["status"] == "ok"
    assert body["agent_skill_plane"]["status"] == "NOT_CONFIGURED"


def test_health_fails_closed_when_agent_plane_is_required(monkeypatch):
    import memory_permanent.api as api_module
    from memory_permanent.agent_skill_plane import RegistryError

    class MissingAgentPlane:
        def __init__(self):
            raise RegistryError("MEMORIA-PERMANENTE project root with .agents was not found")

    monkeypatch.setattr(api_module, "AgentSkillPlane", MissingAgentPlane)
    monkeypatch.setenv("MEMORY_REQUIRE_AGENT_SKILL_PLANE", "true")
    body = api_module.health()
    assert body["status"] == "degraded"
    assert body["agent_skill_plane"]["status"] == "UNHEALTHY"

def test_default_health_identity_is_v55_construction(monkeypatch):
    import memory_permanent.api as api_module

    monkeypatch.delenv("MEMORY_RUNTIME_PROFILE", raising=False)
    monkeypatch.delenv("MEMORY_RELEASE_CHANNEL", raising=False)
    body = api_module.health()
    assert body["runtime_profile"] == "V5.5-CONSTRUCTION"
    assert body["release_channel"] == "v5.5-construction"
    assert "V4" not in body["runtime_profile"]
