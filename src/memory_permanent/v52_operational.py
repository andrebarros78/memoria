from __future__ import annotations

from typing import Any

SCOPE_LABELS = {
    "GLOBAL_USER": "Memória global do usuário",
    "PROJECT": "Memória de projeto",
    "MISSION": "Memória de missão",
    "SESSION": "Memória de sessão",
}
LIFECYCLE_LABELS = {
    "HOT": "Ativa para uso imediato",
    "WARM": "Disponível com menor prioridade",
    "COLD": "Arquivada operacionalmente",
    "DELETE_ELIGIBLE": "Elegível para descarte governado; não é exclusão física",
    "PURGED": "Expurgada por processo governado",
}


def _s(value: Any) -> str:
    return "" if value is None else str(value)


def _truncate(value: Any, limit: int = 180) -> str:
    text = " ".join(_s(value).split())
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def scope_label(scope: Any, ref: Any = None) -> str:
    normalized = _s(scope or "GLOBAL_USER").upper()
    base = SCOPE_LABELS.get(normalized, normalized or "Memória")
    ref_text = _s(ref).strip()
    return base if not ref_text else f"{base}: {ref_text}"


def lifecycle_label(state: Any) -> str:
    normalized = _s(state or "UNKNOWN").upper()
    return LIFECYCLE_LABELS.get(normalized, normalized)


def confidence_label(confidence: Any) -> str:
    try:
        pct = round(float(confidence or 0) * 100)
    except (TypeError, ValueError):
        pct = 0
    if pct >= 85:
        level = "alta"
    elif pct >= 60:
        level = "média"
    else:
        level = "baixa"
    return f"{pct}% · confiança {level}"


def human_memory_card(item: dict[str, Any]) -> dict[str, Any]:
    scope = _s(item.get("memory_scope") or "GLOBAL_USER").upper()
    title = _s(item.get("memory_key") or item.get("item_id") or "Memória sem chave")
    content = item.get("content_text") or item.get("content") or ""
    lifecycle = _s(item.get("lifecycle_state") or "UNKNOWN").upper()
    operator_class = _s(item.get("operator_class") or "UNKNOWN").upper()
    return {
        "item_id": _s(item.get("item_id")),
        "title": title,
        "subtitle": _truncate(content, 140),
        "namespace": _s(item.get("namespace")),
        "scope": scope,
        "scope_ref": item.get("memory_scope_ref"),
        "scope_label": scope_label(scope, item.get("memory_scope_ref")),
        "isolation_boundary": "GLOBAL" if scope == "GLOBAL_USER" else "PROJECT_OR_CONTEXT_BOUNDARY",
        "operator_class": operator_class,
        "lifecycle_state": lifecycle,
        "lifecycle_label": lifecycle_label(lifecycle),
        "confidence_label": confidence_label(item.get("confidence")),
        "source": _s(item.get("source")),
        "tags": list(item.get("tags") or []),
        "usage": {
            "retrievals": int(item.get("retrieval_count") or 0),
            "applications": int(item.get("application_count") or 0),
            "success_rate": item.get("success_rate"),
            "last_used_at": item.get("last_used_at"),
        },
        "temporal": {
            "occurred_at": item.get("occurred_at"),
            "observed_at": item.get("observed_at"),
            "valid_from": item.get("valid_from"),
            "valid_to": item.get("valid_to"),
        },
        "safe_to_show_primary_id": False,
    }


def explain_selected_item(item: dict[str, Any], rank: int) -> dict[str, Any]:
    reasons: list[str] = []
    text_rank = item.get("text_rank")
    similarity = item.get("semantic_similarity") or item.get("similarity")
    try:
        if text_rank is not None and float(text_rank) > 0:
            reasons.append("correspondência lexical")
    except (TypeError, ValueError):
        pass
    try:
        if similarity is not None and float(similarity) > 0:
            reasons.append("similaridade semântica")
    except (TypeError, ValueError):
        pass
    if item.get("memory_scope"):
        reasons.append("escopo permitido")
    if item.get("content_sha256"):
        reasons.append("conteúdo versionado por SHA-256")
    if item.get("confidence") is not None:
        reasons.append(confidence_label(item.get("confidence")))
    return {
        "rank": rank,
        "item_id": _s(item.get("item_id")),
        "human_title": _s(item.get("memory_key") or item.get("item_id")),
        "scope_label": scope_label(item.get("memory_scope"), item.get("memory_scope_ref")),
        "lifecycle_label": lifecycle_label(item.get("lifecycle_state")),
        "authority": _s((item.get("provenance") or {}).get("authority_tier") if isinstance(item.get("provenance"), dict) else ""),
        "text_rank": text_rank,
        "semantic_similarity": similarity,
        "why_selected": reasons or ["selecionada pelo ranking determinístico do Context Engine"],
        "content_preview": _truncate(item.get("content_text"), 180),
    }


def build_retrieval_explanation(*, query: str, selected: list[dict[str, Any]], conflicts: list[dict[str, Any]], retrieval_modes: list[str], trace_id: str | None) -> dict[str, Any]:
    modes = [str(m).upper() for m in retrieval_modes]
    return {
        "contract": "RETRIEVAL_EXPLAINABILITY_V1",
        "trace_id": trace_id,
        "query_preview": _truncate(query, 240),
        "retrieval_modes": modes,
        "selected_count": len(selected),
        "conflict_count": len(conflicts),
        "decision_summary": "PASS" if selected and not conflicts else ("EMPTY" if not selected else "CONFLICT_REVIEW"),
        "ranking_policy": "score determinístico por correspondência lexical, similaridade semântica, confiança, escopo e temporalidade",
        "selected": [explain_selected_item(item, idx + 1) for idx, item in enumerate(selected)],
        "conflicts": conflicts,
        "auditability": {
            "trace_persisted": bool(trace_id),
            "selected_items_include_hashes": all(bool(item.get("content_sha256")) for item in selected),
            "scope_visible": all(bool(item.get("memory_scope")) for item in selected),
        },
    }


def build_human_memory_view(summary: dict[str, Any], items: list[dict[str, Any]], *, latest_trace: dict[str, Any] | None, observability: dict[str, Any]) -> dict[str, Any]:
    cards = [human_memory_card(item) for item in items]
    by_scope: dict[str, int] = {}
    for card in cards:
        by_scope[card["scope_label"]] = by_scope.get(card["scope_label"], 0) + 1
    return {
        "contract": "V5.2_HUMAN_OPERATIONAL_VIEW",
        "health": summary.get("health", "UNKNOWN"),
        "summary": summary,
        "human_identity": {
            "primary_grouping": "scope_label",
            "technical_ids_are_secondary": True,
            "items_total": len(cards),
            "by_scope_label": by_scope,
        },
        "memories": cards,
        "retrieval_explainability": {
            "latest_trace_id": (latest_trace or {}).get("trace_id"),
            "latest_query": (latest_trace or {}).get("query_text"),
            "latest_selected_count": len((latest_trace or {}).get("selected") or []),
            "latest_modes": list((latest_trace or {}).get("retrieval_modes") or []),
        },
        "observability": observability,
    }
