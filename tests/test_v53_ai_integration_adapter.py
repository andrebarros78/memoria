import pytest

from memory_permanent.ai_integration_adapter import (
    AI_INTEGRATION_CONTRACT,
    ai_integration_spec,
    ensure_promotable_memory_create,
    normalize_ai_suggestion,
)


def test_v53_spec_is_adapter_not_internal_ai_api():
    spec = ai_integration_spec()
    assert spec["contract"] == AI_INTEGRATION_CONTRACT
    assert spec["internal_ai_api_created"] is False
    assert spec["external_ai_direct_memory_write"] is False
    assert spec["external_ai_direct_database_access"] is False
    assert "PROMOTE_THROUGH_CANONICAL_MUTATION_SERVICE" in spec["mandatory_flow"]


def test_memory_create_suggestion_is_normalized_but_not_directly_written():
    normalized = normalize_ai_suggestion(
        external_system_id="market-intelligence-ai",
        external_trace_id="trace-001",
        suggestion_type="MEMORY_CREATE",
        confidence=0.91,
        payload={
            "namespace": "market",
            "memory_key": "cliente.preferencia",
            "category": "FACT",
            "content": {"texto": "preferencia validada"},
            "content_text": "Cliente prefere resumo executivo em portugues.",
            "memory_scope": "PROJECT",
            "memory_scope_ref": "MARKET_INTELLIGENCE",
            "tags": ["cliente", "resumo"],
        },
    )
    assert normalized["contract"] == AI_INTEGRATION_CONTRACT
    assert normalized["review"]["requires_acceptance_before_promotion"] is True
    assert normalized["review"]["external_ai_direct_write"] is False
    assert normalized["memory"]["namespace"] == "MARKET"
    assert normalized["memory"]["memory_scope"] == "PROJECT"
    assert ensure_promotable_memory_create(normalized)["memory_key"] == "cliente.preferencia"


def test_review_only_suggestion_is_not_promotable():
    normalized = normalize_ai_suggestion(
        external_system_id="external-ai",
        external_trace_id="trace-002",
        suggestion_type="CONFLICT_REVIEW",
        confidence=0.8,
        payload={"summary": "possivel conflito", "labels": ["conflito"]},
    )
    assert normalized["promotion"]["allowed_after_acceptance"] is False
    with pytest.raises(ValueError):
        ensure_promotable_memory_create(normalized)


@pytest.mark.parametrize("kind", ["DELETE", "PURGE", "MEMORY_DELETE", "DROP"])
def test_destructive_suggestion_types_are_rejected(kind):
    with pytest.raises(ValueError):
        normalize_ai_suggestion(
            external_system_id="external-ai",
            external_trace_id=f"trace-{kind}",
            suggestion_type=kind,
            payload={"namespace": "X", "memory_key": "Y", "content_text": "Z"},
        )


def test_external_ai_cannot_request_direct_control():
    with pytest.raises(ValueError):
        normalize_ai_suggestion(
            external_system_id="external-ai",
            external_trace_id="trace-direct",
            suggestion_type="MEMORY_CREATE",
            payload={"namespace": "X", "memory_key": "Y", "content_text": "Z", "direct_database_access": True},
        )
