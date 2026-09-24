from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
BASE = "http://127.0.0.1:8787"


def http_json(path: str, *, payload: dict | None = None) -> tuple[int, dict]:
    body = None
    headers = {}
    method = "GET"
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
        return resp.status, json.loads(resp.read().decode("utf-8"))


async def prove_mcp() -> dict:
    python = ROOT / ".venv" / "Scripts" / "python.exe"
    params = StdioServerParameters(
        command=str(python),
        args=["-m", "memory_permanent.mcp_server"],
        env=dict(os.environ),
        cwd=ROOT,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            init = await session.initialize()
            listed = await session.list_tools()
            names = sorted(tool.name for tool in listed.tools)
            result = await session.call_tool("memory_summary", {})
            is_error = bool(getattr(result, "isError", False) or getattr(result, "is_error", False))
            return {
                "server_name": getattr(init.server_info, "name", None),
                "tools": names,
                "summary_call_ok": not is_error,
            }


def main() -> int:
    health_status, health = http_json("/health")
    openapi_status, openapi = http_json("/openapi.json")
    context_status, context = http_json(
        "/v1/context/retrieve",
        payload={"query": "P3 retrieval runtime", "namespaces": ["PROOF"], "limit": 10},
    )
    paths = set(openapi.get("paths", {}).keys())
    required_paths = {
        "/v1/memories",
        "/v1/context/retrieve",
        "/v1/memories/classify",
        "/v1/reports/operational.md",
    }
    selected_ids = {str(item.get("item_id")) for item in context.get("selected", [])}
    poisoned_selected = any(item.get("memory_key") == "p3:poison:runtime" for item in context.get("selected", []))
    mcp_result = asyncio.run(prove_mcp())
    required_tools = {"memory_summary", "memory_search", "memory_list"}

    proof = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "rest_health": health_status == 200 and health.get("status") == "ok",
        "openapi_status": openapi_status,
        "openapi_title": openapi.get("info", {}).get("title"),
        "openapi_required_paths_present": required_paths.issubset(paths),
        "rest_context_status": context_status,
        "rest_context_trace_persisted": bool(context.get("trace_id")),
        "rest_poison_not_selected": not poisoned_selected,
        "rest_selected_count": len(selected_ids),
        "mcp_server_name": mcp_result["server_name"],
        "mcp_tools": mcp_result["tools"],
        "mcp_required_tools_present": required_tools.issubset(set(mcp_result["tools"])),
        "mcp_summary_call_ok": mcp_result["summary_call_ok"],
    }
    proof["P4_MEMORY_GATEWAY_PROOF"] = "PASS" if all(
        [
            proof["rest_health"],
            proof["openapi_required_paths_present"],
            proof["rest_context_status"] == 200,
            proof["rest_context_trace_persisted"],
            proof["rest_poison_not_selected"],
            proof["mcp_server_name"] == "memoria-permanente",
            proof["mcp_required_tools_present"],
            proof["mcp_summary_call_ok"],
        ]
    ) else "FAIL"

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "P4_MEMORY_GATEWAY_PROOF.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    return 0 if proof["P4_MEMORY_GATEWAY_PROOF"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
