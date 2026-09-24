from memory_permanent.api import app
from memory_permanent.v55_runtime import (
    CONFORMANCE_CHECKS,
    SECURITY_LAYERS,
    evaluate_conformance,
    v55_runtime_spec,
    validate_profile_selection,
)


def test_v55_runtime_closes_all_eight_points_and_security_depth():
    spec = v55_runtime_spec()
    assert spec["architecture_generation"] == "V5.5"
    assert spec["runtime_profile"] == "V5.5-PRIMARY"
    assert spec["release_channel"] == "MEMORIA_PERMANENTE_CANONICAL_1.0"
    assert spec["product_class"] == "UNIVERSAL_CONTEXT_MEMORY_INFRASTRUCTURE"
    assert spec["closure_points_count"] == 8
    assert len(spec["closure_points"]) == 8
    assert spec["all_official_adapters_available"] is True
    assert spec["ai_required_for_core"] is False
    assert spec["direct_external_database_access"] is False
    assert len(SECURITY_LAYERS) >= 10
    assert spec["security_layer_count"] >= 10
    assert set(spec["universal_operations"]) == {
        "memory.capture",
        "memory.context",
        "memory.search",
        "memory.checkpoint",
        "memory.resume",
        "memory.state",
    }


def test_v55_profiles_cover_whatsapp_and_full_ai_without_changing_contract():
    simple = validate_profile_selection("co_located", ["CORE", "CONVERSATIONAL"])
    assert simple["ai_required"] is False
    assert "conversation_context" in simple["expanded_capabilities"]
    assert simple["contract_changes_required"] is False

    complex_profile = validate_profile_selection("shared_service", ["FULL"])
    assert complex_profile["ai_required"] is True
    assert "semantic_retrieval" in complex_profile["expanded_capabilities"]
    assert "recovery" in complex_profile["expanded_capabilities"]
    assert complex_profile["contract_changes_required"] is False


def test_v55_conformance_requires_every_gate():
    full = evaluate_conformance({name: True for name in CONFORMANCE_CHECKS})
    assert full.compatible is True
    assert full.failed == ()

    partial = evaluate_conformance({"CAPTURE": True, "CONTEXT_RECOVERY": True})
    assert partial.compatible is False
    assert "NEGATIVE_SCOPE_ISOLATION" in partial.failed
    assert "RESTART_RECOVERY" in partial.failed


def test_v55_runtime_contract_is_exposed_by_api():
    paths = app.openapi()["paths"]
    assert "/v1/v5.5/runtime" in paths
    assert "/v1/v5.5/consumer-adapter" in paths
    assert "/v1/v5.5/conversational-adapter" in paths
    assert "/v1/v5.5/profiles/validate" in paths
    assert "/v1/v5.5/conformance/evaluate" in paths
