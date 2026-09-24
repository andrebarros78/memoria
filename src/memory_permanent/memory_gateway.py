from __future__ import annotations

from datetime import datetime
from typing import Any

from .canonical_mutation import CanonicalMutationRequired, CanonicalMutationService
from .context_engine import ContextEngine, ContextResult
from .input_guard import INPUT_GUARD_VERSION, InputGuard
from .provenance_policy import is_system_assigned_trust
from .secret_sanitizer import LocalEncryptedVault, SecretSanitizer


class MemoryGateway:
    """Public boundary between consumers and sovereign memory context."""

    def __init__(self, context_engine: ContextEngine, input_guard: InputGuard | None = None) -> None:
        self.context_engine = context_engine
        self.input_guard = input_guard or InputGuard()
        self.mutations = CanonicalMutationService(context_engine.store, actor_id="memory-gateway")

    def _sanitize_mutation(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        store = self.context_engine.store
        tenant_id = str(getattr(store, "tenant_id", "LEGACY"))
        sanitizer = SecretSanitizer(LocalEncryptedVault.from_environment(), tenant_id)
        content = dict(kwargs.get("content") or {})
        content_text = str(kwargs.get("content_text") or "")
        provenance = dict(kwargs.get("provenance") or {})

        sanitizer.refs = []
        clean_content = sanitizer.sanitize(content)
        clean_text = sanitizer.sanitize(content_text)
        clean_provenance = sanitizer.sanitize(provenance)
        secret_refs = sorted(set(sanitizer.refs))

        result = dict(kwargs)
        result["content"] = clean_content
        result["content_text"] = clean_text
        if secret_refs:
            clean_provenance["secret_refs"] = secret_refs
            clean_provenance["secret_sanitized"] = True
        result["provenance"] = clean_provenance
        return result

    def remember(self, **kwargs: Any) -> str:
        raise CanonicalMutationRequired("MemoryGateway generic write disabled; use CanonicalMutationService.remember_authenticated/internal")

    def revise(self, item_id: str, **kwargs: Any) -> dict[str, Any]:
        raise CanonicalMutationRequired("MemoryGateway generic revise disabled; use CanonicalMutationService.revise_authenticated")

    def retrieve_context(
        self,
        query: str,
        *,
        namespaces: tuple[str, ...],
        limit: int = 8,
        mission_id: str | None = None,
        session_id: str | None = None,
        valid_at: datetime | None = None,
        known_at: datetime | None = None,
    ) -> ContextResult:
        raw = self.context_engine.retrieve(
            query,
            namespaces=namespaces,
            limit=limit,
            mission_id=mission_id,
            session_id=session_id,
            valid_at=valid_at,
            known_at=known_at,
        )
        conflict_keys = {str(conflict.get("memory_key")) for conflict in raw.conflicts}
        records = [dict(item) for item in raw.selected]
        trusted_flags: list[bool] = []
        conflict_flags: list[bool] = []
        for item in records:
            provenance = item.get("provenance") or item.get("provenance_json") or {}
            if isinstance(provenance, str):
                provenance = {"raw": provenance}
            trusted_flags.append(is_system_assigned_trust(provenance))
            conflict_flags.append(str(item.get("memory_key")) in conflict_keys)

        decisions = self.input_guard.assess_batch(
            records,
            trusted_flags=trusted_flags,
            conflict_flags=conflict_flags,
        )

        accepted: list[dict[str, Any]] = []
        quarantined: list[dict[str, Any]] = []
        for item, decision in zip(records, decisions, strict=False):
            enriched = {
                **item,
                "input_guard": {
                    "version": INPUT_GUARD_VERSION,
                    "decision": decision.decision,
                    "reason": decision.reason,
                    "risk_score": decision.risk_score,
                },
            }
            if decision.decision == "QUARANTINE":
                quarantined.append(enriched)
            else:
                accepted.append(enriched)

        conflicts = list(raw.conflicts)
        if quarantined:
            distributed_attack = any(
                "DISTRIBUTED_ATTACK" in str(item["input_guard"].get("reason") or "")
                for item in quarantined
            )
            conflicts.append(
                {
                    "resolution": "QUARANTINED_BY_INPUT_GUARD",
                    "input_guard_version": INPUT_GUARD_VERSION,
                    "distributed_attack": distributed_attack,
                    "batch_reason": "DISTRIBUTED_ATTACK" if distributed_attack else "ITEM_LEVEL_ATTACK",
                    "items": quarantined,
                }
            )
        return ContextResult(
            query=raw.query,
            selected=tuple(accepted),
            conflicts=tuple(conflicts),
            trace_id=raw.trace_id,
            state=raw.state,
            retrieval_modes=raw.retrieval_modes,
        )
