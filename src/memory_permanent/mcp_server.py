from __future__ import annotations

import os
from collections import Counter
from typing import Any
from urllib.parse import urlencode

from mcp.server.mcpserver import MCPServer

from .signed_client import SignedMemoryClient
from .v52_operational import build_retrieval_explanation, human_memory_card

mcp = MCPServer(
    name="memoria-permanente",
    title="MEMORIA-PERMANENTE",
    description="Adapter MCP governado para a infraestrutura universal de memoria V5.5",
    version="0.3.0",
)


def _client() -> SignedMemoryClient:
    base = os.getenv("MEMORY_API_BASE", "http://127.0.0.1:8787").strip()
    client_id = os.getenv("MEMORY_MCP_CLIENT_ID", "mcp-memory-reader").strip()
    if not base or not client_id:
        raise RuntimeError("Memory MCP API client is not configured")
    return SignedMemoryClient(base, client_id)


def _require_ok(status: int, data: Any) -> Any:
    if status != 200:
        raise RuntimeError(f"Memory API returned HTTP {status}: {data}")
    return data


@mcp.tool(name="memory_summary", description="Resume as memorias visiveis pela API soberana sem acesso direto ao banco.")
def memory_summary(project_id: str = "") -> dict[str, Any]:
    headers = {"X-Memory-Project": project_id.strip()} if project_id.strip() else None
    status, data = _client().request("GET", "/v1/memories?limit=500", extra_headers=headers)
    payload = _require_ok(status, data)
    items = list(payload.get("items") or [])
    return {
        "visible_count": len(items),
        "by_scope": dict(Counter(str(item.get("memory_scope") or "UNKNOWN") for item in items)),
        "by_lifecycle": dict(Counter(str(item.get("lifecycle_state") or "UNKNOWN") for item in items)),
        "source": "SIGNED_MEMORY_API",
    }


@mcp.tool(name="memory_search", description="Pesquisa contexto pela API soberana; sem mutacao e sem acesso direto ao PostgreSQL.")
def memory_search(
    query: str,
    namespaces: list[str],
    limit: int = 8,
    project_id: str = "",
    mission_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "namespaces": [str(ns).strip().upper() for ns in namespaces],
        "limit": max(1, min(int(limit), 100)),
    }
    if mission_id.strip():
        payload["mission_id"] = mission_id.strip()
    if session_id.strip():
        payload["session_id"] = session_id.strip()
    headers = {"X-Memory-Project": project_id.strip()} if project_id.strip() else None
    status, data = _client().request("POST", "/v1/context/retrieve", payload, extra_headers=headers)
    result = _require_ok(status, data)
    return {
        "query": result.get("query"),
        "selected": list(result.get("selected") or []),
        "conflicts": list(result.get("conflicts") or []),
        "trace_id": result.get("trace_id"),
        "retrieval_modes": list(result.get("retrieval_modes") or []),
    }


@mcp.tool(name="memory_list", description="Lista memorias pela API soberana com filtros read-only.")
def memory_list(query: str = "", operator_class: str = "", limit: int = 100, project_id: str = "") -> dict[str, Any]:
    params: dict[str, str | int] = {"limit": max(1, min(int(limit), 500))}
    if query.strip():
        params["query"] = query.strip()
    if operator_class.strip():
        params["operator_class"] = operator_class.strip().upper()
    path = "/v1/memories?" + urlencode(params)
    headers = {"X-Memory-Project": project_id.strip()} if project_id.strip() else None
    status, data = _client().request("GET", path, extra_headers=headers)
    return _require_ok(status, data)


@mcp.tool(name="memory_human_view", description="Mostra memorias em formato humano por escopo legivel, mantendo IDs tecnicos como detalhe secundario.")
def memory_human_view(limit: int = 80, project_id: str = "") -> dict[str, Any]:
    params = {"limit": max(1, min(int(limit), 300))}
    path = "/v1/memories?" + urlencode(params)
    headers = {"X-Memory-Project": project_id.strip()} if project_id.strip() else None
    status, data = _client().request("GET", path, extra_headers=headers)
    payload = _require_ok(status, data)
    items = list(payload.get("items") or [])
    cards = [human_memory_card(item) for item in items]
    by_scope = dict(Counter(str(card.get("scope_label") or "UNKNOWN") for card in cards))
    return {
        "contract": "V5.2_MCP_HUMAN_VIEW",
        "visible_count": len(cards),
        "by_scope_label": by_scope,
        "items": cards,
        "source": "SIGNED_MEMORY_API",
        "direct_database_access": False,
    }


@mcp.tool(name="memory_search_explain", description="Pesquisa contexto e devolve explicabilidade V5.2 via API soberana assinada.")
def memory_search_explain(
    query: str,
    namespaces: list[str],
    limit: int = 8,
    project_id: str = "",
    mission_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "namespaces": [str(ns).strip().upper() for ns in namespaces],
        "limit": max(1, min(int(limit), 100)),
    }
    if mission_id.strip():
        payload["mission_id"] = mission_id.strip()
    if session_id.strip():
        payload["session_id"] = session_id.strip()
    headers = {"X-Memory-Project": project_id.strip()} if project_id.strip() else None
    status, data = _client().request("POST", "/v1/context/retrieve/explain", payload, extra_headers=headers)
    if status == 404:
        status, data = _client().request("POST", "/v1/context/retrieve", payload, extra_headers=headers)
        result = _require_ok(status, data)
        selected = list(result.get("selected") or [])
        conflicts = list(result.get("conflicts") or [])
        modes = list(result.get("retrieval_modes") or [])
        result["explanation"] = build_retrieval_explanation(
            query=str(result.get("query") or query),
            selected=selected,
            conflicts=conflicts,
            retrieval_modes=modes,
            trace_id=result.get("trace_id"),
        )
        return result
    return _require_ok(status, data)


@mcp.tool(name="memory_ai_integration_spec", description="Mostra o contrato V5.3 de integracao com IA externa sem criar API de IA interna.")
def memory_ai_integration_spec() -> dict[str, Any]:
    status, data = _client().request("GET", "/v1/ai-integration/spec")
    payload = _require_ok(status, data)
    payload["source"] = "SIGNED_MEMORY_API"
    payload["direct_database_access"] = False
    return payload


if __name__ == "__main__":
    mcp.run("stdio")
