from memory_permanent.api import app, product_universality_identity
from memory_permanent.product_universality import (
    ARCHITECTURE_GENERATION,
    PRODUCT_CLASS,
    UNIVERSAL_PRODUCT_CONTRACT,
    V5_5_CLOSURE_POINTS,
    product_universality_spec,
)


def test_product_universality_contract_is_explicit():
    spec = product_universality_spec()
    assert spec["contract"] == UNIVERSAL_PRODUCT_CONTRACT
    assert spec["architecture_generation"] == ARCHITECTURE_GENERATION == "V5.5"
    assert spec["is_universal_product"] is True
    assert spec["runtime_identity_binding"] is False
    assert spec["consumer_identity_binding"] is False
    assert spec["ai_engine_identity_binding"] is False
    assert spec["ai_required_for_core"] is False
    assert spec["product_class"] == PRODUCT_CLASS == "UNIVERSAL_CONTEXT_MEMORY_INFRASTRUCTURE"
    assert spec["current_proven_runtime"]["meaning"].endswith("not product identity")
    assert "not a Windows-only product" in spec["non_goals"]
    assert "not a Market Intelligence submodule" in spec["non_goals"]
    assert "not a WhatsApp submodule" in spec["non_goals"]
    assert spec["guarantees"]["external_ai_suggests_only"] is True
    assert spec["guarantees"]["memory_governs_promotions"] is True
    assert spec["guarantees"]["direct_external_database_access"] is False
    assert spec["guarantees"]["consumer_decoupling"] is True
    assert spec["guarantees"]["co_located_or_remote_deployment"] is True
    assert spec["guarantees"]["ai_optional_and_replaceable"] is True
    assert spec["v5_5_closure_points"] == V5_5_CLOSURE_POINTS
    assert len(spec["v5_5_closure_points"]) == 8


def test_v5_5_profiles_cover_simple_and_complex_consumers():
    spec = product_universality_spec()
    assert set(spec["deployment_profiles"]) == {"co_located", "dedicated_host", "shared_service", "distributed_ha"}
    assert {"CORE", "CONVERSATIONAL", "AI", "OPERATIONAL", "INTELLIGENCE", "FULL"} <= set(spec["capability_profiles"])
    assert "whatsapp_api" in spec["consumer_systems"]
    assert "market_intelligence_ai" in spec["consumer_systems"]
    assert "lmcp" in spec["consumer_systems"]
    assert "wmcp" in spec["consumer_systems"]


def test_product_universality_is_public_api_contract():
    paths = app.openapi()["paths"]
    assert "/v1/product-universality" in paths
    spec = product_universality_identity()
    assert spec["contract"] == "MEMORIA_PERMANENTE_UNIVERSAL_PRODUCT_V2"
    assert spec["product_id"] == "memoria-permanente"
    assert spec["architecture_generation"] == "V5.5"
