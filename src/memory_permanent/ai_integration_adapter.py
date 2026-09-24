from __future__ import annotations

import hashlib
import json
from typing import Any

AI_INTEGRATION_CONTRACT = "V5.3_AI_INTEGRATION_ADAPTER"
AI_INTEGRATION_PROTOCOL = "AI_SUGGESTS_MEMORY_GOVERNS_V1"
AI_SUGGESTION_TYPES = {"MEMORY_CREATE","MEMORY_REVISE","MEMORY_CLASSIFY","MEMORY_ARCHIVE","DUPLICATE_REVIEW","CONFLICT_REVIEW","SUMMARY"}
PROMOTABLE_TYPES = {"MEMORY_CREATE"}
_ALLOWED_SCOPES = {"GLOBAL_USER", "PROJECT", "MISSION", "SESSION"}
_ALLOWED_CATEGORIES = {"FACT", "PREFERENCE", "PROCEDURE", "DECISION", "EXPERIENCE", "CONSTRAINT", "OBSERVATION"}
_FORBIDDEN_CONTROL_KEYS = {"direct_write","direct_db_access","direct_database_access","bypass_gateway","bypass_policy","override_policy","raw_sql","sql_statement","database_url"}
_FORBIDDEN_SUGGESTION_TYPES = {"MEMORY_DELETE", "MEMORY_PURGE", "PURGE", "DELETE", "ERASE", "DROP"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _s(value: Any, *, max_len: int = 1000) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) > max_len:
        raise ValueError("field exceeds maximum length")
    return text


def _confidence(value: Any, fallback: float = 0.5) -> float:
    try:
        number = float(value if value is not None else fallback)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid confidence") from exc
    if not 0.0 <= number <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return number


def _tags(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else []
    out: list[str] = []
    for item in raw:
        tag = _s(item, max_len=80).upper()
        if tag and tag not in out:
            out.append(tag)
    return out[:100]


def _forbidden_controls(payload: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            name = str(key).strip().lower()
            here = f"{path}.{name}"
            if name in _FORBIDDEN_CONTROL_KEYS and value not in (False, None, "", [], {}):
                found.append(here)
            found.extend(_forbidden_controls(value, here))
    elif isinstance(payload, list):
        for i, item in enumerate(payload[:200]):
            found.extend(_forbidden_controls(item, f"{path}[{i}]"))
    return found


def ai_integration_spec() -> dict[str, Any]:
    return {
        "contract": AI_INTEGRATION_CONTRACT,
        "protocol": AI_INTEGRATION_PROTOCOL,
        "internal_ai_api_created": False,
        "external_ai_direct_database_access": False,
        "external_ai_direct_memory_write": False,
        "role": "Receber sugestoes de IA externa e submeter ao nucleo soberano da memoria.",
        "allowed_suggestion_types": sorted(AI_SUGGESTION_TYPES),
        "promotable_types": sorted(PROMOTABLE_TYPES),
        "mandatory_flow": ["RECEIVE_EXTERNAL_SUGGESTION","NORMALIZE","SANITIZE","PERSIST_APPEND_ONLY","REVIEW_OR_POLICY_ACCEPT","PROMOTE_THROUGH_CANONICAL_MUTATION_SERVICE","AUDIT"],
        "guards": {"hmac_required": True, "rls_required": True, "append_only_evidence": True, "promotion_requires_acceptance": True, "no_delete_or_purge_suggestion": True},
    }


def normalize_ai_suggestion(*, external_system_id: str, external_trace_id: str, suggestion_type: str, payload: dict[str, Any], target_item_id: str | None = None, confidence: float = 0.5, rationale: str = "", model_ref: str | None = None) -> dict[str, Any]:
    system = _s(external_system_id, max_len=120)
    trace = _s(external_trace_id, max_len=240)
    kind = _s(suggestion_type, max_len=80).upper()
    if not system or not trace:
        raise ValueError("external identity required")
    if kind in _FORBIDDEN_SUGGESTION_TYPES or kind not in AI_SUGGESTION_TYPES:
        raise ValueError("suggestion type is not accepted by V5.3")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    violations = _forbidden_controls(payload)
    if violations:
        raise ValueError("suggestion attempted forbidden control: " + ",".join(violations[:8]))
    target = _s(target_item_id, max_len=160) if target_item_id else None
    if kind in {"MEMORY_REVISE", "MEMORY_CLASSIFY", "MEMORY_ARCHIVE"} and not target:
        raise ValueError("target_item_id required for target-bound suggestion")
    effective_confidence = min(_confidence(confidence, 0.5), _confidence(payload.get("confidence"), confidence))
    normalized: dict[str, Any] = {
        "contract": AI_INTEGRATION_CONTRACT,
        "protocol": AI_INTEGRATION_PROTOCOL,
        "external_system_id": system,
        "external_trace_id": trace,
        "suggestion_type": kind,
        "target_item_id": target,
        "confidence": effective_confidence,
        "rationale": _s(rationale or payload.get("rationale"), max_len=4000),
        "model_ref": _s(model_ref or payload.get("model_ref"), max_len=240) or None,
        "payload_sha256": payload_sha256(payload),
        "review": {"status": "READY_FOR_REVIEW", "requires_acceptance_before_promotion": True, "external_ai_direct_write": False, "external_ai_direct_database_access": False},
        "risk": {"level": "LOW" if effective_confidence >= 0.75 else "MEDIUM", "reasons": [] if effective_confidence >= 0.75 else ["LOWER_CONFIDENCE_REQUIRES_REVIEW"]},
    }
    if kind == "MEMORY_CREATE":
        namespace = _s(payload.get("namespace"), max_len=120).upper()
        memory_key = _s(payload.get("memory_key"), max_len=300)
        content_text = _s(payload.get("content_text"), max_len=200000)
        category = _s(payload.get("category") or "FACT", max_len=40).upper()
        scope = _s(payload.get("memory_scope") or "GLOBAL_USER", max_len=40).upper()
        if not namespace or not memory_key or not content_text:
            raise ValueError("MEMORY_CREATE requires namespace, memory_key and content_text")
        if category not in _ALLOWED_CATEGORIES:
            raise ValueError("unsupported memory category")
        if scope not in _ALLOWED_SCOPES:
            raise ValueError("unsupported memory scope")
        normalized["memory"] = {"namespace": namespace, "memory_key": memory_key, "category": category, "content": payload.get("content") if isinstance(payload.get("content"), dict) else {}, "content_text": content_text, "memory_scope": scope, "memory_scope_ref": _s(payload.get("memory_scope_ref"), max_len=240) or None, "confidence": effective_confidence, "source_version": _s(payload.get("source_version"), max_len=120) or None, "tags": _tags(payload.get("tags")), "sharing_scope": _s(payload.get("sharing_scope") or "SYSTEM_SHARED", max_len=40), "owner_user_id": _s(payload.get("owner_user_id"), max_len=160) or None, "owner_agent_id": _s(payload.get("owner_agent_id"), max_len=160) or None, "project_id": _s(payload.get("project_id"), max_len=160) or None, "team_id": _s(payload.get("team_id"), max_len=160) or None, "organization_id": _s(payload.get("organization_id"), max_len=160) or None}
        normalized["promotion"] = {"allowed_after_acceptance": True, "method": "MEMORY_CREATE_CANONICAL"}
    else:
        normalized["analysis"] = {"summary": _s(payload.get("summary") or payload.get("finding") or "", max_len=4000), "labels": _tags(payload.get("labels") or payload.get("tags"))}
        normalized["promotion"] = {"allowed_after_acceptance": False, "method": "REVIEW_ONLY"}
    return normalized


def ensure_promotable_memory_create(normalized: dict[str, Any]) -> dict[str, Any]:
    if str(normalized.get("contract")) != AI_INTEGRATION_CONTRACT:
        raise ValueError("invalid AI integration contract")
    if str(normalized.get("suggestion_type")) != "MEMORY_CREATE":
        raise ValueError("only MEMORY_CREATE suggestions are promotable in V5.3")
    if not isinstance(normalized.get("memory"), dict) or not normalized.get("promotion", {}).get("allowed_after_acceptance"):
        raise ValueError("suggestion is not promotable")
    return dict(normalized["memory"])
