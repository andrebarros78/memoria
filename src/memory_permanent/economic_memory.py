from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

ECONOMIC_MEMORY_VERSION = "EM-1.0.0"


class EconomicEntityType(StrEnum):
    PRODUCT = "PRODUCT"
    SKU = "SKU"
    CAMPAIGN = "CAMPAIGN"
    AD = "AD"


class EconomicStateType(StrEnum):
    INVENTORY = "INVENTORY"
    MARGIN = "MARGIN"
    CAPITAL = "CAPITAL"


class EconomicMetricType(StrEnum):
    REVENUE = "REVENUE"
    COST = "COST"
    PROFIT = "PROFIT"
    ROI = "ROI"
    ROAS = "ROAS"
    CONTRIBUTION_MARGIN = "CONTRIBUTION_MARGIN"
    INVENTORY_VALUE = "INVENTORY_VALUE"
    CAPITAL_RETURN = "CAPITAL_RETURN"
    CUSTOM = "CUSTOM"


class EconomicAttributionSource(StrEnum):
    SOVEREIGN_DECISION = "SOVEREIGN_DECISION"
    EXPERIENCE_INTERVENTION = "EXPERIENCE_INTERVENTION"
    EXPERIENCE_EVIDENCE = "EXPERIENCE_EVIDENCE"
    ECONOMIC_ENTITY = "ECONOMIC_ENTITY"
    ECONOMIC_STATE = "ECONOMIC_STATE"


def _decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be a finite decimal")
    return result


def decimal_text(value: Any, name: str = "value") -> str:
    result = _decimal(value, name)
    return format(result, "f")


def normalize_currency(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    currency = str(value).strip().upper()
    if len(currency) != 3 or not currency.isalpha() or not currency.isascii():
        raise ValueError("currency must be a 3-letter ISO-style code")
    return currency


def validate_entity_record(*, entity_type: str, external_ref: str, attributes: dict[str, Any]) -> dict[str, Any]:
    kind = EconomicEntityType(str(entity_type).strip().upper())
    ref = str(external_ref or "").strip()
    if not ref or len(ref) > 300:
        raise ValueError("economic entity external_ref is required and must be <= 300 chars")
    if not isinstance(attributes, dict):
        raise ValueError("economic entity attributes must be an object")
    return {"entity_type": kind.value, "external_ref": ref, "attributes": dict(attributes)}


def validate_state_record(
    *, state_type: str, value: Any, unit: str, currency: str | None, metadata: dict[str, Any]
) -> dict[str, Any]:
    kind = EconomicStateType(str(state_type).strip().upper())
    amount = _decimal(value, "economic state value")
    unit_value = str(unit or "").strip().upper()
    if not unit_value or len(unit_value) > 40:
        raise ValueError("economic state unit is required and must be <= 40 chars")
    if kind in {EconomicStateType.INVENTORY, EconomicStateType.CAPITAL} and amount < 0:
        raise ValueError(f"{kind.value} value cannot be negative")
    if not isinstance(metadata, dict):
        raise ValueError("economic state metadata must be an object")
    currency_value = normalize_currency(currency)
    if unit_value in {"MONEY", "CURRENCY"} and currency_value is None:
        raise ValueError("monetary economic state requires currency")
    return {
        "state_type": kind.value,
        "value": format(amount, "f"),
        "unit": unit_value,
        "currency": currency_value,
        "metadata": dict(metadata),
    }


def validate_attributions(attributions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(attributions, list) or not attributions:
        raise ValueError("economic result requires at least one attribution")
    normalized: list[dict[str, Any]] = []
    total = Decimal(0)
    seen: set[tuple[str, str]] = set()
    for raw in attributions:
        if not isinstance(raw, dict):
            raise ValueError("economic attribution must be an object")
        source_kind = EconomicAttributionSource(str(raw.get("source_kind") or "").strip().upper())
        source_id = str(raw.get("source_id") or "").strip()
        if not source_id or len(source_id) > 240:
            raise ValueError("economic attribution source_id is required and must be <= 240 chars")
        weight = _decimal(raw.get("weight"), "economic attribution weight")
        if weight <= 0 or weight > 1:
            raise ValueError("economic attribution weight must be > 0 and <= 1")
        key = (source_kind.value, source_id)
        if key in seen:
            raise ValueError("duplicate economic attribution source")
        seen.add(key)
        total += weight
        if total > Decimal(1):
            raise ValueError("economic attribution weights cannot exceed 1.0")
        evidence = raw.get("evidence") or {}
        if not isinstance(evidence, dict):
            raise ValueError("economic attribution evidence must be an object")
        normalized.append({
            "source_kind": source_kind.value,
            "source_id": source_id,
            "weight": format(weight, "f"),
            "rationale": str(raw.get("rationale") or "").strip(),
            "evidence": dict(evidence),
        })
    return normalized


def validate_result_record(
    *, mission_id: str, entity_id: str | None, metric_type: str, value: Any, unit: str,
    currency: str | None, proof: dict[str, Any], attributions: list[dict[str, Any]]
) -> dict[str, Any]:
    mission = str(mission_id or "").strip()
    if not mission or len(mission) > 240:
        raise ValueError("economic result mission_id is required and must be <= 240 chars")
    entity = str(entity_id or "").strip() or None
    if entity is not None and len(entity) > 240:
        raise ValueError("economic result entity_id must be <= 240 chars")
    metric = EconomicMetricType(str(metric_type).strip().upper())
    amount = _decimal(value, "economic result value")
    unit_value = str(unit or "").strip().upper()
    if not unit_value or len(unit_value) > 40:
        raise ValueError("economic result unit is required and must be <= 40 chars")
    currency_value = normalize_currency(currency)
    if unit_value in {"MONEY", "CURRENCY"} and currency_value is None:
        raise ValueError("monetary economic result requires currency")
    if not isinstance(proof, dict) or not proof:
        raise ValueError("economic result proof must be a non-empty object")
    normalized_attributions = validate_attributions(attributions)
    return {
        "mission_id": mission,
        "entity_id": entity,
        "metric_type": metric.value,
        "value": format(amount, "f"),
        "unit": unit_value,
        "currency": currency_value,
        "proof": dict(proof),
        "attributions": normalized_attributions,
    }


def economic_spec() -> dict[str, Any]:
    return {
        "version": ECONOMIC_MEMORY_VERSION,
        "entity_types": [x.value for x in EconomicEntityType],
        "state_types": [x.value for x in EconomicStateType],
        "metric_types": [x.value for x in EconomicMetricType],
        "attribution_sources": [x.value for x in EconomicAttributionSource],
        "invariants": [
            "economic results require at least one attribution",
            "attribution weights are > 0 and <= 1 with total <= 1",
            "decision/intervention/evidence attribution is resolved and snapshotted server-side",
            "all economic domain rows are tenant-isolated, append-only and bitemporal",
            "created_at is persistence time and never substitutes valid_from",
        ],
    }
