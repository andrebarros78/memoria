from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

DECISION_RECORD_VERSION = "DR-1.1.0"


class DecisionCriticality(StrEnum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_alternatives(alternatives: list[dict[str, Any]], criticality: str | DecisionCriticality) -> list[dict[str, Any]]:
    crit = DecisionCriticality(str(criticality).strip().upper())
    if not isinstance(alternatives, list) or not alternatives:
        raise ValueError("decision alternatives must contain at least one structured alternative")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for alt in alternatives:
        if not isinstance(alt, dict):
            raise ValueError("each decision alternative must be an object")
        alt_id = str(alt.get("id") or "").strip()
        label = str(alt.get("label") or "").strip()
        if not alt_id or not label:
            raise ValueError("each decision alternative requires id and label")
        if alt_id in seen:
            raise ValueError("decision alternative ids must be unique")
        seen.add(alt_id)
        normalized.append({**alt, "id": alt_id, "label": label})
    if crit is DecisionCriticality.CRITICAL and len(normalized) < 2:
        raise ValueError("critical decisions require at least two alternatives")
    return normalized


def validate_action(action: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise ValueError("decision action must be an object")
    action_type = str(action.get("type") or "").strip()
    target = str(action.get("target") or "").strip()
    parameters = action.get("parameters", {})
    if not action_type or not target:
        raise ValueError("decision action requires type and target")
    if not isinstance(parameters, dict):
        raise ValueError("decision action parameters must be an object")
    return {**action, "type": action_type, "target": target, "parameters": parameters}


def validate_decision_record(
    *,
    objective: str,
    alternatives: list[dict[str, Any]],
    rationale: str,
    action: dict[str, Any],
    expected_outcome: dict[str, Any],
    proof: dict[str, Any],
    evidence_refs: list[dict[str, Any]],
    criticality: str | DecisionCriticality,
) -> dict[str, Any]:
    crit = DecisionCriticality(str(criticality).strip().upper())
    objective_value = str(objective or "").strip()
    rationale_value = str(rationale or "").strip()
    if not objective_value:
        raise ValueError("decision objective is required")
    if not rationale_value:
        raise ValueError("decision rationale is required")
    if not isinstance(expected_outcome, dict) or not expected_outcome:
        raise ValueError("decision expected_outcome must be a non-empty object")
    if not isinstance(proof, dict) or not proof:
        raise ValueError("decision proof must be a non-empty object")
    refs = list(evidence_refs or [])
    if crit is DecisionCriticality.CRITICAL and not refs:
        raise ValueError("critical decisions require at least one evidence reference")
    return {
        "criticality": crit.value,
        "objective": objective_value,
        "alternatives": validate_alternatives(alternatives, crit),
        "rationale": rationale_value,
        "action": validate_action(action),
        "expected_outcome": dict(expected_outcome),
        "proof": dict(proof),
        "evidence_refs": refs,
    }


def authority_snapshot(principal: Any, tenant_id: str) -> dict[str, Any]:
    permissions = sorted(map(str, getattr(principal, "permissions", frozenset())))
    if "*" in permissions or "memory:admin" in permissions:
        tier = "ADMIN"
    elif "memory:validate" in permissions:
        tier = "VALIDATOR"
    else:
        tier = "AUTHENTICATED"
    return {
        "client_id": str(getattr(principal, "client_id", "unknown")),
        "authority_tier": tier,
        "tenant_id": str(tenant_id),
        "permissions": permissions,
    }


def _canonical_timestamp(value: str) -> str:
    raw=str(value or '').strip()
    if not raw:
        raise ValueError("decision occurred_at is required")
    dt=datetime.fromisoformat(raw.replace('Z','+00:00'))
    if dt.tzinfo is None:
        raise ValueError("decision occurred_at must be timezone-aware")
    return dt.astimezone(UTC).isoformat()


def decision_core_material(
    *,
    mission_id: str,
    mission_anchor_type: str,
    mission_anchor_id: str,
    mission_snapshot: dict[str, Any],
    criticality: str,
    objective: str,
    context: dict[str, Any],
    alternatives: list[dict[str, Any]],
    rationale: str,
    authority: dict[str, Any],
    action: dict[str, Any],
    expected_outcome: dict[str, Any],
    proof: dict[str, Any],
    occurred_at: str,
) -> dict[str, Any]:
    return {
        "record_version": DECISION_RECORD_VERSION,
        "mission_id": mission_id,
        "mission_anchor_type": mission_anchor_type,
        "mission_anchor_id": mission_anchor_id,
        "mission_snapshot": mission_snapshot,
        "criticality": criticality,
        "objective": objective,
        "context": context,
        "alternatives": alternatives,
        "rationale": rationale,
        "authority": authority,
        "action": action,
        "expected_outcome": expected_outcome,
        "proof": proof,
        "occurred_at": _canonical_timestamp(occurred_at),
    }


def build_replay_package(decision: dict[str, Any], evidence: list[dict[str, Any]], outcomes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    package = {
        "record_version": DECISION_RECORD_VERSION,
        "decision_id": decision["decision_id"],
        "mission_id": decision["mission_id"],
        "mission_anchor_type": decision["mission_anchor_type"],
        "mission_anchor_id": decision["mission_anchor_id"],
        "mission_snapshot": decision["mission_snapshot"],
        "criticality": decision["criticality"],
        "objective": decision["objective"],
        "context": decision["decision_context"],
        "alternatives": decision["alternatives"],
        "rationale": decision["rationale"],
        "authority": decision["authority"],
        "action": decision["action"],
        "expected_outcome": decision["expected_outcome"],
        "decision_proof": decision["decision_proof"],
        "decision_core_sha256": decision["core_sha256"],
        "actual_outcomes": [
            {
                "decision_outcome_id": row["decision_outcome_id"],
                "success": row["success"],
                "actual_outcome": row["actual_outcome"],
                "proof": row["proof"],
                "occurred_at": row["occurred_at"],
                "recorded_by": row["recorded_by"],
            }
            for row in (outcomes or [])
        ],
        "evidence": [
            {
                "role": row["role"],
                "item_id": row["item_id"],
                "version_id": row["version_id"],
                "version_no": row["version_no"],
                "content_sha256": row["content_sha256"],
                "category_snapshot": row["category_snapshot"],
                "snapshot": row["evidence_snapshot"],
            }
            for row in evidence
        ],
    }
    return {**package, "replay_sha256": sha256_json(package)}
