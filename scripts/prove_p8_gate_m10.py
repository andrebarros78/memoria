from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
GOV = Path(r"C:\New Projet\GOVERNADOR-WINDOWS")


def load(name: str) -> dict[str, Any]:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8-sig"))


def pass_key(data: dict[str, Any], prefix: str) -> bool:
    if any(str(k).startswith(prefix) and v == "PASS" for k, v in data.items()):
        return True
    return any(isinstance(v, str) and v.endswith("=PASS") for v in data.values())


def scan_active_consumer() -> dict[str, Any]:
    files = [
        GOV / "src" / "governor_windows" / "runtime_components.py",
        GOV / "src" / "governor_windows" / "engineer_runtime.py",
        GOV / "src" / "governor_windows" / "cli.py",
        GOV / "src" / "governor_windows" / "service.py",
        GOV / "src" / "governor_windows" / "memory_client_adapter.py",
    ]
    forbidden_imports = (
        "from .memory_gateway",
        "from .context_engine",
        "from governor_windows.memory_gateway",
        "from governor_windows.context_engine",
        "from memory_permanent",
        "import memory_permanent",
    )
    direct_db_markers = ("psycopg", "55436", "MEMORY_DATABASE_URL", "pgpass.conf")
    findings: list[dict[str, str]] = []
    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        for marker in forbidden_imports:
            if marker in text:
                findings.append({"file": str(path), "type": "FORBIDDEN_IMPORT", "marker": marker})
        if path.name == "memory_client_adapter.py":
            for marker in direct_db_markers:
                if marker in text:
                    findings.append({"file": str(path), "type": "DIRECT_DB_COUPLING", "marker": marker})
    cfg = json.loads((GOV / "config" / "governor.json").read_text(encoding="utf-8-sig"))
    endpoint = str((cfg.get("memory_gateway") or {}).get("endpoint") or "")
    return {
        "files_checked": [str(p) for p in files],
        "findings": findings,
        "finding_count": len(findings),
        "memory_gateway_endpoint": endpoint,
        "endpoint_is_public_contract": endpoint.startswith(("http://", "https://")),
        "governor_config_contains_memory_db_port": "55436" in json.dumps(cfg, ensure_ascii=False),
    }


def main() -> int:
    p1 = load("P1_STRUCTURE_PROOF.json")
    p2 = load("P2_DB_SERVICE_ISOLATION_PROOF.json")
    p3 = load("P3_REUSED_COMPONENTS_PROOF.json")
    p4 = load("P4_MEMORY_GATEWAY_PROOF.json")
    p5 = load("P5_MEMORY_CLIENT_ADAPTER_PROOF.json")
    p5reg = load("P5_GOVERNOR_REGRESSION_PROOF.json")
    p6a = load("P6_MEMORY_OFFLINE_WMCP_ALIVE.json")
    p6b = load("P6_GOVERNOR_OFFLINE_MEMORY_ALIVE.json")
    p6c = load("P6_WMCP_OFFLINE_MEMORY_ALIVE.json")
    p7 = load("P7_DATA_MIGRATION_PROOF.json")
    api_restart = load("PANEL_API_RESTART_PROOF.json")
    live = load("P8_LIVE_RUNTIME_STATE.json")
    wmcp = load("P8_WMCP_CURRENT_HEALTH.json")
    active = scan_active_consumer()

    checks = {
        "P1_INDEPENDENT_MODULE": pass_key(p1, "P1_"),
        "P2_DB_ISOLATION": pass_key(p2, "P2_"),
        "P3_REUSED_COMPONENTS": pass_key(p3, "P3_"),
        "P4_PUBLIC_GATEWAY": pass_key(p4, "P4_"),
        "P5_CLIENT_ADAPTER": pass_key(p5, "P5_"),
        "P5_GOVERNOR_REGRESSION": pass_key(p5reg, "P5_"),
        "P6_MEMORY_OFFLINE_WMCP_ALIVE": pass_key(p6a, "P6_"),
        "P6_GOVERNOR_OFFLINE_MEMORY_ALIVE": pass_key(p6b, "P6_"),
        "P6_WMCP_OFFLINE_MEMORY_ALIVE": pass_key(p6c, "P6_"),
        "P7_DATA_MIGRATION": pass_key(p7, "P7_"),
        "PANEL_API_RESTART": pass_key(api_restart, "PANEL_API_"),
        "ACTIVE_CONSUMER_NO_INTERNAL_COUPLING": active["finding_count"] == 0,
        "PUBLIC_MEMORY_ENDPOINT": bool(active["endpoint_is_public_contract"]),
        "NO_MEMORY_DB_PORT_IN_GOVERNOR_CONFIG": not bool(active["governor_config_contains_memory_db_port"]),
        "MEMORY_PG_RUNNING": live.get("memory_pg_service_state") == "Running",
        "MEMORY_PG_AUTOSTART": live.get("memory_pg_start_mode") == "Auto",
        "MEMORY_DB_READY": live.get("memory_db_ready") is True,
        "GOVERNOR_DB_READY": live.get("governor_db_ready") is True,
        "MEMORY_API_RUNNING": live.get("api_task_state") == "Running" and live.get("memory_api_health") == "ok",
        "WMCP_CURRENTLY_HEALTHY": wmcp.get("status") == "ok" and wmcp.get("safe_probe") is True,
        "MIGRATION_DATA_LOSS_ZERO": p7.get("memory_manifest_match") is True and p7.get("unexplained_duplication") == 0,
        "GOVERNOR_RELEASE_TRUSTED": p5reg.get("trust_guard_ok") is True and int(p5reg.get("release_generation") or 0) >= 36,
    }

    gate_pass = all(checks.values())
    result = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "gate": "M10",
        "objective": "MEMORY_MODULE_INDEPENDENCE_PROVEN",
        "checks": checks,
        "failed_checks": [k for k, v in checks.items() if not v],
        "active_consumer_scan": active,
        "memory_count_live_snapshot": live.get("memory_count"),
        "governor_release_generation": p5reg.get("release_generation"),
        "postgres_runtime_version_note": "Current development runtime PostgreSQL 17.10; V4 release target 18.6 remains a separate homologation requirement and is not part of M10 independence semantics.",
        "GATE_M10": "PASS" if gate_pass else "FAIL",
        "MEMORY_MODULE_INDEPENDENCE_PROVEN": gate_pass,
    }
    (EVIDENCE / "P8_GATE_M10_PROOF.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Gate M10 — Memory Module Independence Proof",
        "",
        f"**Generated:** {result['generated_at']}",
        f"**GATE_M10:** {result['GATE_M10']}",
        f"**MEMORY_MODULE_INDEPENDENCE_PROVEN:** {str(gate_pass).upper()}",
        "",
        "## Checks",
        "",
    ]
    lines.extend(f"- `{name}`: {'PASS' if ok else 'FAIL'}" for name, ok in checks.items())
    lines += [
        "",
        "## Consumer boundary",
        "",
        f"- Active consumer coupling findings: `{active['finding_count']}`",
        f"- Memory Gateway endpoint: `{active['memory_gateway_endpoint']}`",
        f"- Governor release generation: `{p5reg.get('release_generation')}`",
        "",
        "## Migration integrity",
        "",
        f"- Source memory manifest: `{p7.get('source_memory_manifest_sha256')}`",
        f"- Target memory manifest: `{p7.get('target_memory_manifest_sha256')}`",
        f"- Unexplained duplication: `{p7.get('unexplained_duplication')}`",
        "",
        "## Runtime note",
        "",
        result["postgres_runtime_version_note"],
    ]
    (EVIDENCE / "P8_GATE_M10_PROOF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if gate_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
