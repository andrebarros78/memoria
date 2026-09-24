from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
BASE = "http://127.0.0.1:8787"


def get_json(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(BASE + path, timeout=5) as response:  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
        return json.loads(response.read().decode("utf-8"))


def get_text(path: str) -> tuple[int, str, str]:
    with urllib.request.urlopen(BASE + path, timeout=5) as response:  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
        return response.status, response.headers.get_content_type(), response.read().decode("utf-8")


def post_json(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as response:  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
        return response.status, json.loads(response.read().decode("utf-8"))


def load(name: str) -> dict[str, Any]:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8-sig"))


def main() -> int:
    health = get_json("/health")
    summary_before = get_json("/v1/dashboard/summary")
    panel_status, panel_type, panel_html = get_text("/")
    report_status, report_type, report_md = get_text("/v1/reports/operational.md")
    openapi = get_json("/openapi.json")

    query = urllib.parse.quote("proof:permanent")
    items = get_json(f"/v1/memories?q={query}&limit=20").get("items") or []
    proof_item = next((item for item in items if item.get("memory_key") == "proof:permanent"), None)
    classification_ok = False
    classification_response: dict[str, Any] | None = None
    if proof_item:
        status, classification_response = post_json(
            "/v1/memories/classify",
            {
                "item_ids": [proof_item["item_id"]],
                "operator_class": "PERMANENTE",
                "changed_by": "panel-operational-gate-proof",
            },
        )
        classification_ok = (
            status == 200
            and classification_response.get("operator_class") == "PERMANENTE"
            and classification_response.get("lifecycle_state") == "HOT"
            and classification_response.get("direct_delete") is False
        )

    purge_blocked = False
    purge_status = None
    req = urllib.request.Request(BASE + "/v1/purge", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5)  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
    except urllib.error.HTTPError as exc:
        purge_status = exc.code
        purge_blocked = exc.code == 405

    summary_after = get_json("/v1/dashboard/summary")
    css = (ROOT / "src" / "memory_permanent" / "static" / "styles.css").read_text(encoding="utf-8")
    html_required = all(
        token in panel_html
        for token in ("Painel Operacional", "PERMANENTE", "ATIVA", "ARQUIVADA", "DESCARTÁVEL", "PROTEGIDA", "Relatório .MD")
    )
    responsive_css = "@media" in css and len(css) >= 5000

    core = load("PAINEL_OPERATIONAL_PROOF.json")
    restart = load("PANEL_API_RESTART_PROOF.json")
    gate_m10 = load("P8_GATE_M10_PROOF.json")

    checks = {
        "HEALTH_OK": health.get("status") == "ok",
        "PANEL_HTTP_200": panel_status == 200 and panel_type == "text/html",
        "PANEL_REQUIRED_CONTROLS": html_required,
        "PANEL_RESPONSIVE_STYLES": responsive_css,
        "SUMMARY_REAL_DATA": int(summary_after.get("memories_total") or 0) >= 126,
        "LIVE_CLASSIFICATION": classification_ok,
        "CLASSIFICATION_DID_NOT_DELETE": summary_after.get("memories_total") == summary_before.get("memories_total"),
        "MARKDOWN_REPORT": report_status == 200 and "markdown" in report_type and len(report_md) > 200,
        "DIRECT_PURGE_BLOCKED": purge_blocked,
        "OPENAPI_PRESENT": openapi.get("info", {}).get("title") == "MEMORIA-PERMANENTE",
        "CORE_PROOF": core.get("PANEL_CORE_PROOF") == "PASS",
        "API_RESTART_PROOF": restart.get("PANEL_API_RESTART_PROOF") == "PASS",
        "M10_INDEPENDENCE": gate_m10.get("GATE_M10") == "PASS",
    }
    proven = all(checks.values())
    result = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "checks": checks,
        "failed_checks": [k for k, v in checks.items() if not v],
        "memories_total": summary_after.get("memories_total"),
        "operator_classes": summary_after.get("operator_classes"),
        "classification_response": classification_response,
        "report_bytes": len(report_md.encode("utf-8")),
        "purge_status": purge_status,
        "PAINEL_OPERATIONAL_PROVEN": "PASS" if proven else "FAIL",
        "V5_PANEL_PRIORITY_CRITERION_SATISFIED": proven,
    }
    (EVIDENCE / "PAINEL_OPERATIONAL_GATE_PROOF.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (EVIDENCE / "PAINEL_LIVE_REPORT.md").write_text(report_md, encoding="utf-8")

    lines = [
        "# Painel Operacional — Gate de Comprovação",
        "",
        f"**Gerado em:** {result['generated_at']}",
        f"**PAINEL_OPERATIONAL_PROVEN:** {result['PAINEL_OPERATIONAL_PROVEN']}",
        "",
        "## Checks",
        "",
    ]
    lines.extend(f"- `{name}`: {'PASS' if ok else 'FAIL'}" for name, ok in checks.items())
    lines += [
        "",
        f"- Memórias em runtime: `{result['memories_total']}`",
        f"- Purge direto HTTP: `{purge_status}` (esperado 405)",
        f"- Relatório live: `{result['report_bytes']}` bytes",
    ]
    (EVIDENCE / "PAINEL_OPERATIONAL_GATE_PROOF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if proven else 1


if __name__ == "__main__":
    raise SystemExit(main())
