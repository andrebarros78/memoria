from memory_permanent.conversational_adapter import (
    CONVERSATIONAL_ADAPTER_CONTRACT,
    ConversationalContextAdapter,
    conversational_adapter_spec,
)


def test_conversational_adapter_is_provider_neutral_and_ai_optional():
    spec = conversational_adapter_spec()
    assert spec["contract"] == CONVERSATIONAL_ADAPTER_CONTRACT
    assert spec["provider_neutral"] is True
    assert spec["requires_ai"] is False
    assert spec["direct_database_access"] is False
    assert "WHATSAPP_API" in spec["supported_consumer_classes"]


def test_whatsapp_like_event_normalizes_into_governed_session_memory():
    payload = ConversationalContextAdapter().normalize_message(
        provider="whatsapp",
        conversation_id="5515999999999",
        message_id="wamid.abc123",
        participant_id="customer-42",
        direction="inbound",
        text="Quero saber o status do meu pedido",
        project_id="whatsapp-sales-ai",
        session_id="session-77",
        metadata={"channel": "whatsapp-api"},
    )
    assert payload["namespace"] == "CONVERSATION"
    assert payload["category"] == "OBSERVATION"
    assert payload["memory_scope"] == "SESSION"
    assert payload["memory_scope_ref"] == "session-77"
    assert payload["project_id"] == "whatsapp-sales-ai"
    assert payload["source"] == "conversation:whatsapp"
    assert payload["provenance"]["adapter_contract"] == CONVERSATIONAL_ADAPTER_CONTRACT
    assert payload["governor_eligible"] is False


def test_conversational_adapter_uses_project_scope_without_session():
    payload = ConversationalContextAdapter().normalize_message(
        provider="crm",
        conversation_id="conv-1",
        message_id="msg-1",
        participant_id="customer-1",
        direction="outbound",
        text="Seu atendimento foi concluído.",
        project_id="crm-project",
    )
    assert payload["memory_scope"] == "PROJECT"
    assert payload["memory_scope_ref"] == "crm-project"
