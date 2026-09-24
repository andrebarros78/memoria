import pytest

from memory_permanent.access_policy import AgentAccessContext
from memory_permanent.api import app


def test_agent_private_requires_matching_agent():
    ctx=AgentAccessContext.build(agent_id='agent-a')
    value=ctx.validate_scope('AGENT_PRIVATE', owner_agent_id='agent-a')
    assert value['owner_agent_id']=='agent-a'
    with pytest.raises(PermissionError):
        ctx.validate_scope('AGENT_PRIVATE', owner_agent_id='agent-b')


def test_team_and_project_scopes_are_bound_to_actor_context():
    ctx=AgentAccessContext.build(agent_id='agent-a', team_id='team-1', project_id='project-1')
    assert ctx.validate_scope('AGENT_TEAM')['team_id']=='team-1'
    assert ctx.validate_scope('PROJECT_SHARED')['project_id']=='project-1'
    with pytest.raises(PermissionError):
        ctx.validate_scope('PROJECT_SHARED', project_id='project-2')


def test_private_user_and_org_are_not_implicit_global():
    ctx=AgentAccessContext.build(user_id='user-1', organization_id='org-1')
    assert ctx.validate_scope('PRIVATE_USER')['owner_user_id']=='user-1'
    assert ctx.validate_scope('ORGANIZATION_SHARED')['organization_id']=='org-1'


def test_multiagent_lease_routes_are_public_contract():
    paths=set(app.openapi()['paths'])
    assert '/v1/leases/{lease_key}/acquire' in paths
    assert '/v1/leases/{lease_key}/release' in paths
