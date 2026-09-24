from __future__ import annotations

import os

from fastapi import HTTPException, Request

from .access_policy import AgentAccessContext
from .client_auth import principal_from_request
from .store import PostgresMemoryStore


def authenticated_store(
    request: Request,
    *,
    tenant: str | None = None,
    agent: str | None = None,
    user: str | None = None,
    project: str | None = None,
    team: str | None = None,
    organization: str | None = None,
) -> PostgresMemoryStore:
    principal = principal_from_request(request)
    claims = principal.resolve_claims(
        tenant=tenant,
        agent=agent,
        user=user,
        project=project,
        team=team,
        organization=organization,
    )
    dsn = os.getenv("MEMORY_DATABASE_URL", "").strip()
    if not dsn:
        raise HTTPException(status_code=503, detail="MEMORY_DATABASE_URL not configured")
    try:
        access = AgentAccessContext.build(
            agent_id=claims["agent"],
            user_id=claims["user"],
            project_id=claims["project"],
            team_id=claims["team"],
            organization_id=claims["organization"],
        )
        return PostgresMemoryStore(dsn, tenant_id=str(claims["tenant"]), access=access, initialize=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid authenticated memory access context") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Memory Store unavailable: {type(exc).__name__}") from exc
