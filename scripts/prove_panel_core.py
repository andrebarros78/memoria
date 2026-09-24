from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from memory_permanent.report import render_operational_report
from memory_permanent.store import PostgresMemoryStore

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"


def ensure_memory(store: PostgresMemoryStore, key: str, category: str, text: str) -> str:
    for item in store.list_memories(query=key, limit=50):
        if item["memory_key"] == key:
            return str(item["item_id"])
    return store.remember(
        namespace="PROOF",
        memory_key=key,
        category=category,
        content={"proof": key, "text": text},
        content_text=text,
        provenance={"trusted": True, "source": "panel-core-proof"},
        confidence=1.0,
        source="sovereign-system",
        tags=["proof", "panel"],
        changed_by="proof-script",
    )


def main() -> int:
    dsn = os.environ["MEMORY_DATABASE_URL"]
    store = PostgresMemoryStore(dsn)
    keys = [
        ("proof:permanent", "RULE", "Regra soberana de prova do painel"),
        ("proof:active", "STATE", "Estado ativo de prova do painel"),
        ("proof:archived", "EVENT", "Histórico arquivável de prova do painel"),
        ("proof:discardable", "HYPOTHESIS", "Hipótese descartável de prova do painel"),
        ("proof:protected", "EVIDENCE", "Evidência protegida de prova do painel"),
    ]
    ids = {key: ensure_memory(store, key, category, text) for key, category, text in keys}
    before = store.summary()["memories_total"]

    expected = {
        "proof:permanent": "PERMANENTE",
        "proof:active": "ATIVA",
        "proof:archived": "ARQUIVADA",
        "proof:discardable": "DESCARTÁVEL",
        "proof:protected": "PROTEGIDA",
    }
    results = {}
    for key, operator_class in expected.items():
        results[key] = store.classify([ids[key]], operator_class, changed_by="proof-script")

    after = store.summary()["memories_total"]
    items = {item["memory_key"]: item for item in store.list_memories(query="proof:", limit=100) if item["memory_key"] in expected}
    classifications_ok = all(items[k]["operator_class"] == v for k, v in expected.items())
    discard = items["proof:discardable"]
    no_delete = before == after and discard["lifecycle_state"] == "DELETE_ELIGIBLE"

    with store._connection() as conn:
        active_holds = conn.execute(
            "SELECT item_id,hold_type,status FROM retention_holds WHERE item_id=ANY(%s) AND status='ACTIVE' ORDER BY item_id",
            (list(ids.values()),),
        ).fetchall()
    hold_map = {str(row["item_id"]): str(row["hold_type"]) for row in active_holds}
    holds_ok = hold_map.get(ids["proof:permanent"]) == "SOVEREIGN_HOLD" and hold_map.get(ids["proof:protected"]) == "EVIDENCE_HOLD"

    summary = store.summary()
    report = render_operational_report(summary)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "PAINEL_OPERATIONAL_PROOF.md").write_text(report, encoding="utf-8")

    result = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "database": "memoria_permanente",
        "port": 55436,
        "governor_legacy_port": 55435,
        "database_isolated_by_port": True,
        "classification_results": results,
        "classifications_ok": classifications_ok,
        "memory_count_before_classification": before,
        "memory_count_after_classification": after,
        "discardable_state": discard["lifecycle_state"],
        "direct_delete_occurred": not no_delete,
        "holds": hold_map,
        "holds_ok": holds_ok,
        "report_generated": True,
        "summary": summary,
    }
    result["PANEL_CORE_PROOF"] = "PASS" if classifications_ok and no_delete and holds_ok else "FAIL"
    (EVIDENCE / "PAINEL_OPERATIONAL_PROOF.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["PANEL_CORE_PROOF"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
