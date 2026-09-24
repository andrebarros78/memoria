from __future__ import annotations

from memory_permanent.api import app
from memory_permanent.client_auth import required_permission_for_path
from memory_permanent.v52_operational import (
    build_human_memory_view,
    build_retrieval_explanation,
    human_memory_card,
    lifecycle_label,
    scope_label,
)


def sample_item(**overrides):
    item = {
        "item_id": "mem-1",
        "namespace": "QA_RETRIEVAL_V1",
        "memory_key": "projeto.painel.operacional",
        "content_text": "Painel deve mostrar memórias por nome humano e não por UUID técnico.",
        "memory_scope": "PROJECT",
        "memory_scope_ref": "MEMORIA_PERMANENTE_IA_SISTEMAS",
        "operator_class": "PERMANENTE",
        "lifecycle_state": "HOT",
        "confidence": 0.91,
        "retrieval_count": 3,
        "application_count": 2,
        "success_rate": 100.0,
        "content_sha256": "a" * 64,
        "provenance": {"authority_tier": "VALIDATED"},
    }
    item.update(overrides)
    return item


def test_scope_and_lifecycle_labels_are_human_first() -> None:
    assert scope_label("GLOBAL_USER") == "Memória global do usuário"
    assert scope_label("PROJECT", "P1") == "Memória de projeto: P1"
    assert "não é exclusão física" in lifecycle_label("DELETE_ELIGIBLE")


def test_human_memory_card_hides_technical_id_as_primary_reference() -> None:
    card = human_memory_card(sample_item())
    assert card["title"] == "projeto.painel.operacional"
    assert card["scope_label"] == "Memória de projeto: MEMORIA_PERMANENTE_IA_SISTEMAS"
    assert card["safe_to_show_primary_id"] is False
    assert card["isolation_boundary"] == "PROJECT_OR_CONTEXT_BOUNDARY"
    assert "91%" in card["confidence_label"]


def test_retrieval_explanation_exposes_why_without_mutation() -> None:
    explanation = build_retrieval_explanation(
        query="painel operacional",
        selected=[sample_item(text_rank=0.7, semantic_similarity=0.82)],
        conflicts=[],
        retrieval_modes=["LEXICAL", "SEMANTIC"],
        trace_id="trace-1",
    )
    assert explanation["contract"] == "RETRIEVAL_EXPLAINABILITY_V1"
    assert explanation["decision_summary"] == "PASS"
    assert explanation["auditability"]["trace_persisted"] is True
    assert "correspondência lexical" in explanation["selected"][0]["why_selected"]
    assert "similaridade semântica" in explanation["selected"][0]["why_selected"]


def test_human_dashboard_contract_groups_by_scope_label() -> None:
    view = build_human_memory_view(
        {"health": "OK", "memories_total": 1},
        [sample_item()],
        latest_trace={"trace_id": "trace-1", "query_text": "q", "selected": [sample_item()], "retrieval_modes": ["LEXICAL"]},
        observability={"status": "PASS"},
    )
    assert view["contract"] == "V5.2_HUMAN_OPERATIONAL_VIEW"
    assert view["human_identity"]["technical_ids_are_secondary"] is True
    assert view["human_identity"]["by_scope_label"] == {"Memória de projeto: MEMORIA_PERMANENTE_IA_SISTEMAS": 1}
    assert view["retrieval_explainability"]["latest_trace_id"] == "trace-1"


def test_v52_routes_and_permissions_are_registered() -> None:
    paths = app.openapi()["paths"]
    assert "/v1/dashboard/human-memory" in paths
    assert "/v1/context/retrieve/explain" in paths
    assert "/v1/observability/v52" in paths
    assert required_permission_for_path("/v1/context/retrieve/explain", "POST") == "memory:context"
    assert required_permission_for_path("/v1/dashboard/human-memory", "GET") == "memory:admin"
    assert required_permission_for_path("/v1/observability/v52", "GET") == "memory:admin"



def test_panel_contains_v52_operational_surfaces() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    html = (root / "src" / "memory_permanent" / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "src" / "memory_permanent" / "static" / "app.js").read_text(encoding="utf-8")
    assert "V5.2 · IDENTIDADE HUMANA" in html
    assert "OBSERVABILIDADE SOBERANA" in html
    assert "'/v1/dashboard/human-memory'" in js
    assert "'/v1/observability/v52'" in js
    assert "loadV52Operational" in js



def test_mcp_server_exposes_v52_human_and_explainability_tools() -> None:
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "src" / "memory_permanent" / "mcp_server.py").read_text(encoding="utf-8")
    assert 'name="memory_human_view"' in source
    assert 'name="memory_search_explain"' in source
    assert "PostgresMemoryStore" not in source
    assert "direct_database_access" in source



def test_health_exposes_runtime_profile_without_changing_product_dna(monkeypatch) -> None:
    from memory_permanent.api import health
    monkeypatch.setenv("MEMORY_RUNTIME_PROFILE", "V5.2-RC1")
    monkeypatch.setenv("MEMORY_RELEASE_CHANNEL", "rc1-parallel")
    body = health()
    assert body["product_id"] == "memoria-permanente"
    assert body["runtime_profile"] == "V5.2-RC1"
    assert body["release_channel"] == "rc1-parallel"
