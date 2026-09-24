from __future__ import annotations

from dataclasses import dataclass

from .memory_scope import normalize_memory_scope

SHARING_SCOPES = {
    "PRIVATE_USER",
    "PROJECT_SHARED",
    "AGENT_PRIVATE",
    "AGENT_TEAM",
    "SYSTEM_SHARED",
    "ORGANIZATION_SHARED",
}


def _norm(value: str | None, *, max_len: int = 160) -> str | None:
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    if len(v) > max_len:
        raise ValueError("access identifier too long")
    return v


@dataclass(frozen=True, slots=True)
class AgentAccessContext:
    agent_id: str | None = None
    user_id: str | None = None
    project_id: str | None = None
    team_id: str | None = None
    organization_id: str | None = None

    @classmethod
    def build(
        cls,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        team_id: str | None = None,
        organization_id: str | None = None,
    ) -> AgentAccessContext:
        return cls(
            agent_id=_norm(agent_id),
            user_id=_norm(user_id),
            project_id=_norm(project_id),
            team_id=_norm(team_id),
            organization_id=_norm(organization_id),
        )

    @classmethod
    def system(cls) -> AgentAccessContext:
        return cls(agent_id="__SYSTEM__")

    def validate_sharing_scope(
        self,
        scope: str,
        *,
        owner_user_id: str | None = None,
        owner_agent_id: str | None = None,
        project_id: str | None = None,
        team_id: str | None = None,
        organization_id: str | None = None,
    ) -> dict[str, str | None]:
        scope = str(scope or "SYSTEM_SHARED").strip().upper()
        if scope not in SHARING_SCOPES:
            raise ValueError("invalid sharing_scope")
        values = {
            "sharing_scope": scope,
            "owner_user_id": _norm(owner_user_id),
            "owner_agent_id": _norm(owner_agent_id),
            "project_id": _norm(project_id),
            "team_id": _norm(team_id),
            "organization_id": _norm(organization_id),
        }
        if self.agent_id == "__SYSTEM__":
            return values
        required = {
            "PRIVATE_USER": ("owner_user_id", self.user_id),
            "PROJECT_SHARED": ("project_id", self.project_id),
            "AGENT_PRIVATE": ("owner_agent_id", self.agent_id),
            "AGENT_TEAM": ("team_id", self.team_id),
            "ORGANIZATION_SHARED": ("organization_id", self.organization_id),
        }.get(scope)
        if required:
            field, actor_value = required
            if values[field] is None:
                values[field] = actor_value
            if actor_value is None or values[field] != actor_value:
                raise PermissionError(f"actor does not own requested {scope} scope")
        return values

    def validate_scope(
        self,
        scope: str,
        *,
        owner_user_id: str | None = None,
        owner_agent_id: str | None = None,
        project_id: str | None = None,
        team_id: str | None = None,
        organization_id: str | None = None,
    ) -> dict[str, str | None]:
        return self.validate_sharing_scope(
            scope, owner_user_id=owner_user_id, owner_agent_id=owner_agent_id, project_id=project_id,
            team_id=team_id, organization_id=organization_id,
        )

    def validate_memory_scope(self, scope: str = "GLOBAL_USER", *, memory_scope_ref: str | None = None) -> dict[str, str | None]:
        semantic_scope, semantic_ref = normalize_memory_scope(scope, memory_scope_ref)
        return {"memory_scope": semantic_scope.value, "memory_scope_ref": semantic_ref}
