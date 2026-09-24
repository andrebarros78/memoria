from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from .signed_client import SignedMemoryClient

CONSUMER_ADAPTER_CONTRACT = "MEMORIA_PERMANENTE_CONSUMER_ADAPTER_V1"


class MemoryTransport(Protocol):
    def request(
        self,
        method: str,
        path_query: str,
        payload: Any | None = None,
        extra_headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> tuple[int, Any]: ...


@dataclass(slots=True)
class UniversalMemoryClientAdapter:
    """Consumer-side adapter for any system using the public Memory API.

    It never imports store/database modules and never receives a PostgreSQL DSN.
    Remote deployments are supported through HTTPS; cleartext HTTP is restricted
    by SignedMemoryClient's network policy to loopback.
    """

    base_url: str
    client_id: str
    transport: MemoryTransport | None = None

    def __post_init__(self) -> None:
        if self.transport is None:
            self.transport = SignedMemoryClient(self.base_url, self.client_id)

    @staticmethod
    def _headers(
        *,
        project_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        organization_id: str | None = None,
    ) -> dict[str, str] | None:
        headers: dict[str, str] = {}
        if project_id:
            headers["X-Memory-Project"] = str(project_id)
        if user_id:
            headers["X-Memory-User"] = str(user_id)
        if agent_id:
            headers["X-Memory-Agent"] = str(agent_id)
        if organization_id:
            headers["X-Memory-Organization"] = str(organization_id)
        return headers or None

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> Any:
        assert self.transport is not None
        status, data = self.transport.request(method, path, payload, extra_headers=headers)
        if not 200 <= int(status) < 300:
            raise RuntimeError(f"Memory API returned HTTP {status}: {data}")
        return data

    def health(self) -> dict[str, Any]:
        return dict(self._request("GET", "/health"))

    def capture(
        self,
        memory: dict[str, Any],
        *,
        project_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
        organization_id: str | None = None,
    ) -> dict[str, Any]:
        return dict(
            self._request(
                "POST",
                "/v1/memories",
                dict(memory),
                headers=self._headers(
                    project_id=project_id,
                    user_id=user_id,
                    agent_id=agent_id,
                    organization_id=organization_id,
                ),
            )
        )

    def context(
        self,
        query: str,
        namespaces: list[str],
        *,
        limit: int = 8,
        project_id: str | None = None,
        user_id: str | None = None,
        mission_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": str(query),
            "namespaces": [str(x).upper() for x in namespaces],
            "limit": max(1, min(int(limit), 100)),
        }
        if mission_id:
            payload["mission_id"] = str(mission_id)
        if session_id:
            payload["session_id"] = str(session_id)
        return dict(
            self._request(
                "POST",
                "/v1/context/retrieve",
                payload,
                headers=self._headers(project_id=project_id, user_id=user_id),
            )
        )

    def search(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.context(*args, **kwargs)

    def checkpoint(
        self,
        checkpoint: dict[str, Any],
        *,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        return dict(
            self._request(
                "POST",
                "/v1/checkpoints",
                dict(checkpoint),
                headers=self._headers(project_id=project_id, user_id=user_id),
            )
        )

    def state(
        self,
        mission_id: str,
        *,
        project_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        path = "/v1/checkpoints/" + quote(str(mission_id), safe="") + "/latest"
        return dict(
            self._request(
                "GET",
                path,
                headers=self._headers(project_id=project_id, user_id=user_id),
            )
        )

    def resume(
        self,
        mission_id: str,
        query: str,
        namespaces: list[str],
        *,
        project_id: str | None = None,
        user_id: str | None = None,
        limit: int = 8,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        checkpoint = self.state(mission_id, project_id=project_id, user_id=user_id)
        context = self.context(
            query,
            namespaces,
            limit=limit,
            project_id=project_id,
            user_id=user_id,
            mission_id=mission_id,
            session_id=session_id,
        )
        return {
            "contract": CONSUMER_ADAPTER_CONTRACT,
            "mission_id": str(mission_id),
            "checkpoint": checkpoint,
            "context": context,
            "direct_database_access": False,
        }


def consumer_adapter_spec() -> dict[str, Any]:
    return {
        "contract": CONSUMER_ADAPTER_CONTRACT,
        "operations": [
            "memory.capture",
            "memory.context",
            "memory.search",
            "memory.checkpoint",
            "memory.resume",
            "memory.state",
        ],
        "transports": ["HTTP_LOOPBACK", "HTTPS_REMOTE"],
        "direct_database_access": False,
        "database_driver_dependency": False,
        "consumer_specific_dependency": False,
    }
