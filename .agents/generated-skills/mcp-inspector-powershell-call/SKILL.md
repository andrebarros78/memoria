---
name: mcp-inspector-powershell-call
description: Invoke MCP Inspector CLI tools/list and tools/call reliably from Windows PowerShell when stdio target argument ordering and quoting must be preserved.
license: Internal project procedure derived from measured experience
compatibility: Windows PowerShell 5.1 or later, MCP Inspector CLI 2.5.0, Python MCP stdio server
---

# MCP Inspector PowerShell Call

## Procedure

1. Use the Inspector CLI entrypoint directly when launcher argument forwarding is ambiguous.
2. Put the stdio target executable and target arguments before the `--` delimiter.
3. Put Inspector options after `--`.
4. Pass `PYTHONPATH` with Inspector `-e` so the spawned MCP server receives it.
5. Run `tools/list` before `tools/call`.
6. Treat success as both process exit code `0` and MCP result `isError=false`.

## Failure handling

If the Inspector reports `Target is required`, inspect argument ordering; do not change the MCP server. If the child reports `ModuleNotFoundError`, pass the required module path through Inspector `-e`.

## Evidence

This skill was derived from a measured failure-to-success transition and is activation-gated by replay, recovery, evaluation and OPA policy.
