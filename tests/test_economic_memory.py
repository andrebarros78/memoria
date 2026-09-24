from __future__ import annotations

import pytest

from memory_permanent.api import app
from memory_permanent.client_auth import required_permission_for_path
from memory_permanent.economic_memory import (
    ECONOMIC_MEMORY_VERSION,
    EconomicAttributionSource,
    EconomicEntityType,
    EconomicMetricType,
    EconomicStateType,
    economic_spec,
    normalize_currency,
    validate_attributions,
    validate_entity_record,
    validate_result_record,
    validate_state_record,
)


def test_economic_memory_version_and_spec() -> None:
    spec=economic_spec()
    assert ECONOMIC_MEMORY_VERSION == "EM-1.0.0"
    assert set(spec["entity_types"]) == {x.value for x in EconomicEntityType}
    assert set(spec["state_types"]) == {x.value for x in EconomicStateType}
    assert set(spec["metric_types"]) == {x.value for x in EconomicMetricType}
    assert set(spec["attribution_sources"]) == {x.value for x in EconomicAttributionSource}


def test_entity_record_is_formal_and_normalized() -> None:
    value=validate_entity_record(entity_type="sku",external_ref="SKU-001",attributes={"name":"Blue"})
    assert value["entity_type"] == "SKU"
    assert value["external_ref"] == "SKU-001"


def test_currency_is_strict_three_letter_code() -> None:
    assert normalize_currency("brl") == "BRL"
    with pytest.raises(ValueError): normalize_currency("R$")
    with pytest.raises(ValueError): normalize_currency("USDT")


def test_inventory_and_capital_cannot_be_negative() -> None:
    for state in ("INVENTORY","CAPITAL"):
        with pytest.raises(ValueError):
            validate_state_record(state_type=state,value="-1",unit="UNITS",currency=None,metadata={})


def test_margin_can_be_negative() -> None:
    value=validate_state_record(state_type="MARGIN",value="-12.50",unit="MONEY",currency="BRL",metadata={})
    assert value["value"] == "-12.50"


def test_monetary_state_requires_currency() -> None:
    with pytest.raises(ValueError):
        validate_state_record(state_type="CAPITAL",value="100",unit="MONEY",currency=None,metadata={})


def test_result_requires_non_empty_proof_and_attribution() -> None:
    with pytest.raises(ValueError):
        validate_result_record(mission_id="m1",entity_id=None,metric_type="PROFIT",value="1",unit="MONEY",currency="BRL",proof={},attributions=[])


def test_result_preserves_decimal_precision() -> None:
    value=validate_result_record(
        mission_id="m1",entity_id="eco-1",metric_type="PROFIT",value="1234567890.123456789",
        unit="MONEY",currency="BRL",proof={"source":"ledger"},
        attributions=[{"source_kind":"SOVEREIGN_DECISION","source_id":"dec-1","weight":"0.75"}],
    )
    assert value["value"] == "1234567890.123456789"
    assert value["attributions"][0]["weight"] == "0.75"


def test_attribution_weight_total_cannot_exceed_one() -> None:
    with pytest.raises(ValueError):
        validate_attributions([
            {"source_kind":"SOVEREIGN_DECISION","source_id":"d1","weight":"0.7"},
            {"source_kind":"EXPERIENCE_INTERVENTION","source_id":"i1","weight":"0.4"},
        ])


def test_duplicate_attribution_source_rejected() -> None:
    with pytest.raises(ValueError):
        validate_attributions([
            {"source_kind":"EXPERIENCE_EVIDENCE","source_id":"e1","weight":"0.4"},
            {"source_kind":"EXPERIENCE_EVIDENCE","source_id":"e1","weight":"0.3"},
        ])


def test_non_finite_numbers_rejected() -> None:
    with pytest.raises(ValueError):
        validate_state_record(state_type="MARGIN",value="NaN",unit="PERCENT",currency=None,metadata={})
    with pytest.raises(ValueError):
        validate_result_record(mission_id="m1",entity_id=None,metric_type="ROI",value="Infinity",unit="RATIO",currency=None,proof={"x":1},attributions=[{"source_kind":"ECONOMIC_ENTITY","source_id":"e","weight":"1"}])


def test_custom_result_can_be_non_monetary_without_currency() -> None:
    value=validate_result_record(mission_id="m1",entity_id=None,metric_type="CUSTOM",value="2.5",unit="RATIO",currency=None,proof={"x":1},attributions=[{"source_kind":"ECONOMIC_ENTITY","source_id":"e","weight":"1"}])
    assert value["currency"] is None


def test_economic_api_and_auth_contract() -> None:
    paths=app.openapi()["paths"]
    for path in ("/v1/economic-memory/spec","/v1/economy/entities","/v1/economy/states","/v1/economy/results","/v1/economy/history"):
        assert path in paths
    assert app.version == "0.29.2"
    assert required_permission_for_path("/v1/economic-memory/spec","GET") == "memory:read"
    assert required_permission_for_path("/v1/economy/results","POST") == "memory:experience"
    assert required_permission_for_path("/v1/economy/history","GET") == "memory:read"
