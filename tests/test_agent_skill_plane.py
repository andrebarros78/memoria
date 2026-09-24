from __future__ import annotations

import pytest

from memory_permanent.agent_skill_plane import AgentSkillPlane, RegistryError

EXPECTED_AGENTS = {
    "memory-steward-agent",
    "memory-evolution-capacity-agent",
    "recovery-integrity-agent",
    "retrieval-quality-agent",
}

EXPECTED_SKILLS = {
    "skill-creator",
    "mcp-builder",
    "phoenix-evals",
    "phoenix-tracing",
    "mcp-inspector-powershell-call",
    "retrieval-quality-validation",
}


def test_agent_skill_plane_discovers_complete_inventory() -> None:
    plane = AgentSkillPlane()
    assert set(plane.agents) == EXPECTED_AGENTS
    assert set(plane.skills) == EXPECTED_SKILLS


def test_every_agent_class_is_loadable() -> None:
    plane = AgentSkillPlane()
    for agent_id, spec in plane.agents.items():
        loaded = plane.load_agent_class(agent_id)
        assert loaded.__name__ == spec.class_name


def test_every_skill_has_real_consumer_and_is_callable() -> None:
    plane = AgentSkillPlane()
    for skill in plane.skills.values():
        assert skill.consumers
        invocation = plane.invoke_skill(skill.consumers[0], skill.name)
        assert invocation["skill"] == skill.name
        assert len(invocation["sha256"]) == 64
        assert invocation["content"].lstrip().startswith("---")


def test_agent_skill_mapping_is_reciprocal() -> None:
    plane = AgentSkillPlane()
    for agent in plane.agents.values():
        for skill_name in agent.allowed_skills:
            assert agent.agent_id in plane.skills[skill_name].consumers


def test_skill_invocation_denies_unauthorized_agent() -> None:
    plane = AgentSkillPlane()
    with pytest.raises(PermissionError):
        plane.invoke_skill("recovery-integrity-agent", "skill-creator")


def test_skill_path_escape_fails_closed() -> None:
    plane = AgentSkillPlane()
    with pytest.raises(RegistryError):
        plane._safe_agent_path("../outside")


def test_agent_skill_health_is_fully_healthy() -> None:
    health = AgentSkillPlane().health()
    assert health == {
        "status": "HEALTHY",
        "agents_total": 4,
        "agents_loaded": 4,
        "skills_total": 6,
        "skills_callable": 6,
        "errors": [],
    }
