from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

CONVERSATIONAL_ADAPTER_CONTRACT = "MEMORIA_PERMANENTE_CONVERSATIONAL_ADAPTER_V1"


def _clean(value: Any, *, max_len: int) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise ValueError("required conversational field is empty")
    if len(text) > max_len:
        raise ValueError("conversational field exceeds maximum length")
    return text


def _sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    provider: str
    conversation_id: str
    message_id: str
    participant_id: str
    direction: str
    text: str
    occurred_at: datetime
    metadata: dict[str, Any]


class ConversationalContextAdapter:
    """Provider-neutral normalizer for WhatsApp/chat/support/CRM consumers.

    It produces a governed memory capture payload only. Persistence remains the
    responsibility of the public Memory API / UniversalMemoryClientAdapter.
    """

    adapter_id = "conversation-v1"

    def normalize_message(
        self,
        *,
        provider: str,
        conversation_id: str,
        message_id: str,
        participant_id: str,
        direction: str,
        text: str,
        namespace: str = "CONVERSATION",
        project_id: str | None = None,
        session_id: str | None = None,
        occurred_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider_value = _clean(provider, max_len=80).lower()
        conversation = _clean(conversation_id, max_len=240)
        message = _clean(message_id, max_len=240)
        participant = _clean(participant_id, max_len=240)
        direction_value = _clean(direction, max_len=20).upper()
        if direction_value not in {"INBOUND", "OUTBOUND", "SYSTEM"}:
            raise ValueError("direction must be INBOUND, OUTBOUND or SYSTEM")
        text_value = _clean(text, max_len=200000)
        when = occurred_at or datetime.now(UTC)
        meta = dict(metadata or {})
        source_payload = {
            "provider": provider_value,
            "conversation_id": conversation,
            "message_id": message,
            "participant_id": participant,
            "direction": direction_value,
            "occurred_at": when.isoformat(),
            "metadata": meta,
        }
        memory_key = f"conversation:{provider_value}:{conversation}:{message}"
        scope = "SESSION" if session_id else ("PROJECT" if project_id else "GLOBAL_USER")
        scope_ref = session_id or project_id
        return {
            "namespace": _clean(namespace, max_len=120).upper(),
            "memory_key": memory_key,
            "category": "OBSERVATION",
            "content": {
                "conversation": source_payload,
                "text": text_value,
            },
            "content_text": text_value,
            "provenance": {
                "kind": "CONVERSATIONAL_EVENT",
                "adapter_contract": CONVERSATIONAL_ADAPTER_CONTRACT,
                "source_sha256": _sha(source_payload),
                "provider": provider_value,
            },
            "confidence": 1.0,
            "source": f"conversation:{provider_value}",
            "source_version": "1",
            "tags": ["CONVERSATION", provider_value.upper(), direction_value],
            "changed_by": f"conversation-adapter:{provider_value}",
            "memory_scope": scope,
            "memory_scope_ref": scope_ref,
            "sharing_scope": "PROJECT_SHARED" if project_id else "PRIVATE_USER",
            "project_id": project_id,
            "occurred_at": when.isoformat(),
            "observed_at": datetime.now(UTC).isoformat(),
            "validation_status": "SOURCE_OBSERVED",
            "governor_eligible": False,
        }


def conversational_adapter_spec() -> dict[str, Any]:
    return {
        "contract": CONVERSATIONAL_ADAPTER_CONTRACT,
        "provider_neutral": True,
        "supported_consumer_classes": ["WHATSAPP_API", "CHAT", "SUPPORT", "SALES", "CRM"],
        "requires_ai": False,
        "direct_database_access": False,
        "persistence_path": "PUBLIC_MEMORY_API",
        "scope_policy": "SESSION_IF_AVAILABLE_ELSE_PROJECT_ELSE_GLOBAL_USER",
    }

