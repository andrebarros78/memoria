from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .client_auth import ClientPrincipal
from .provenance_policy import derive_authenticated_provenance
from .secret_sanitizer import LocalEncryptedVault, SecretSanitizer


class CanonicalMutationRequired(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MutationContext:
    actor_id: str
    operation: str


_ACTIVE_MUTATION: ContextVar[MutationContext | None] = ContextVar("memory_canonical_mutation", default=None)


@contextmanager
def canonical_mutation_scope(actor_id: str, operation: str) -> Iterator[MutationContext]:
    actor = str(actor_id or "unknown").strip() or "unknown"
    op = str(operation or "unknown").strip() or "unknown"
    ctx = MutationContext(actor_id=actor, operation=op)
    token = _ACTIVE_MUTATION.set(ctx)
    try:
        yield ctx
    finally:
        _ACTIVE_MUTATION.reset(token)


def require_canonical_mutation(operation: str) -> MutationContext:
    ctx = _ACTIVE_MUTATION.get()
    if ctx is None:
        raise CanonicalMutationRequired(
            f"persistent mutation '{operation}' must pass through CanonicalMutationService"
        )
    return ctx


class CanonicalMutationService:
    """Single policy boundary for persistent mutations.

    Responsibilities:
    - create the mutation authorization context used by Store/repositories;
    - sanitize every persistent caller-controlled payload before storage;
    - derive provenance from authenticated identity for public memory writes;
    - keep internal writes explicitly attributed instead of self-attested.
    """

    def __init__(self, store: Any, *, actor_id: str = "memory-system") -> None:
        self.store = store
        self.actor_id = str(actor_id or "memory-system")
        tenant_id = str(getattr(store, "tenant_id", "LEGACY"))
        self.sanitizer = SecretSanitizer(LocalEncryptedVault.from_environment(), tenant_id)

    def sanitize(self, value: Any) -> tuple[Any, list[str]]:
        self.sanitizer.refs = []
        clean = self.sanitizer.sanitize(value)
        return clean, sorted(set(self.sanitizer.refs))

    def _sanitize_mapping(self, values: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        clean, refs = self.sanitize(values)
        return dict(clean), refs

    @staticmethod
    def _attach_refs(provenance: dict[str, Any], refs: list[str]) -> dict[str, Any]:
        result = dict(provenance or {})
        if refs:
            existing = list(result.get("secret_refs") or [])
            result["secret_refs"] = sorted(set(existing + refs))
            result["secret_sanitized"] = True
        return result

    def remember_authenticated(
        self,
        *,
        principal: ClientPrincipal,
        asserted_source: str,
        asserted_provenance: dict[str, Any],
        **kwargs: Any,
    ) -> str:
        source, provenance = derive_authenticated_provenance(
            principal, asserted_source=asserted_source, asserted_provenance=asserted_provenance
        )
        payload = dict(kwargs)
        payload["source"] = source
        payload["provenance"] = provenance
        payload["changed_by"] = principal.client_id
        payload["validation_status"] = "UNVALIDATED"
        payload["governor_eligible"] = False
        clean, refs = self._sanitize_mapping(payload)
        clean["provenance"] = self._attach_refs(dict(clean.get("provenance") or {}), refs)
        with canonical_mutation_scope(principal.client_id, "memory.remember"):
            return self.store.remember(**clean)

    def revise_authenticated(
        self,
        item_id: str,
        *,
        principal: ClientPrincipal,
        asserted_source: str,
        asserted_provenance: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        source, provenance = derive_authenticated_provenance(
            principal, asserted_source=asserted_source, asserted_provenance=asserted_provenance
        )
        payload = dict(kwargs)
        payload["source"] = source
        payload["provenance"] = provenance
        payload["changed_by"] = principal.client_id
        clean, refs = self._sanitize_mapping(payload)
        clean["provenance"] = self._attach_refs(dict(clean.get("provenance") or {}), refs)
        with canonical_mutation_scope(principal.client_id, "memory.revise"):
            return self.store.revise(item_id, **clean)

    def remember_internal(
        self,
        *,
        actor_id: str,
        source: str,
        provenance: dict[str, Any],
        trusted: bool = False,
        **kwargs: Any,
    ) -> str:
        asserted = dict(provenance or {})
        asserted.pop("trusted", None)
        asserted.pop("trust", None)
        asserted.pop("trust_assigned_by", None)
        derived = {
            "trusted": bool(trusted),
            "trust_assigned_by": "internal-system",
            "trust": {
                "trusted": bool(trusted),
                "basis": "INTERNAL_SYSTEM_ASSIGNMENT" if trusted else "INTERNAL_UNATTESTED_CHANNEL",
            },
            "internal_actor_id": actor_id,
            "asserted_source": source,
            "asserted_provenance": asserted,
        }
        payload = dict(kwargs)
        payload.update(
            source=str(source), provenance=derived, changed_by=str(actor_id),
            validation_status="UNVALIDATED", governor_eligible=False,
        )
        clean, refs = self._sanitize_mapping(payload)
        clean["provenance"] = self._attach_refs(dict(clean.get("provenance") or {}), refs)
        with canonical_mutation_scope(actor_id, "memory.remember.internal"):
            return self.store.remember(**clean)

    def validate_current_version(self, item_id: str, *, actor_id: str, evidence: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        clean_evidence, _ = self.sanitize(evidence or {})
        with canonical_mutation_scope(actor_id, "memory.validate"):
            return self.store.validate_current_version(item_id, evidence=clean_evidence, **kwargs)

    def record_application(self, item_id: str, *, actor_id: str, context: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        clean_context, _ = self.sanitize(context or {})
        with canonical_mutation_scope(actor_id, "experience.application"):
            return self.store.record_application(item_id, context=clean_context, **kwargs)

    def record_outcome(
        self,
        application_id: str,
        *,
        principal: ClientPrincipal | None = None,
        actor_id: str | None = None,
        expected: dict[str, Any],
        actual: dict[str, Any],
        evidence: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        clean, _ = self._sanitize_mapping({"expected": expected or {}, "actual": actual or {}, "evidence": evidence or {}})
        requested_delta_present = "confidence_delta" in kwargs and kwargs.get("confidence_delta") is not None
        kwargs.pop("confidence_delta", None)
        actor = principal.client_id if principal is not None else str(actor_id or self.actor_id)
        if principal is not None:
            authority_tier = "ATTESTED" if (principal.allows_permission("provenance:attest") or principal.allows_permission("memory:validate")) else "AUTHENTICATED"
        else:
            authority_tier = "INTERNAL"
        with canonical_mutation_scope(actor, "experience.outcome"):
            return self.store.record_outcome(
                application_id, expected=clean["expected"], actual=clean["actual"], evidence=clean["evidence"],
                authority_tier=authority_tier, caller_confidence_delta_present=requested_delta_present, **kwargs,
            )

    def save_checkpoint(self, *, actor_id: str, state: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        clean_state, _ = self.sanitize(state or {})
        with canonical_mutation_scope(actor_id, "checkpoint.save"):
            return self.store.save_checkpoint(state=clean_state, **kwargs)

    def classify(self, item_ids: list[str], operator_class: str, *, actor_id: str) -> dict[str, Any]:
        with canonical_mutation_scope(actor_id, "memory.classify"):
            return self.store.classify(item_ids, operator_class, changed_by=actor_id)

    def record_retrieval_trace(
        self,
        query: str,
        namespaces: list[str],
        candidates: list[dict[str, Any]],
        selected: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
        *,
        state: dict[str, Any] | None,
        retrieval_modes: list[str],
    ) -> str:
        clean, _ = self._sanitize_mapping({
            "query": query, "candidates": candidates, "selected": selected,
            "conflicts": conflicts, "state": state,
        })
        with canonical_mutation_scope(self.actor_id, "retrieval.trace"):
            return self.store.record_retrieval_trace(
                str(clean["query"]), namespaces, list(clean["candidates"]), list(clean["selected"]),
                list(clean["conflicts"]), state=clean["state"], retrieval_modes=retrieval_modes,
            )

    def store_embedding(self, item_id: str, **kwargs: Any) -> None:
        with canonical_mutation_scope(self.actor_id, "embedding.store"):
            self.store.store_embedding(item_id, **kwargs)

    def mark_embedding_failed(self, item_id: str, **kwargs: Any) -> None:
        clean = dict(kwargs)
        if "error_message" in clean:
            clean["error_message"], _ = self.sanitize(str(clean["error_message"]))
        with canonical_mutation_scope(self.actor_id, "embedding.failed"):
            self.store.mark_embedding_failed(item_id, **clean)

    def acquire_lease(self, lease_key: str, **kwargs: Any) -> dict[str, Any]:
        with canonical_mutation_scope(self.actor_id, "lease.acquire"):
            return self.store.acquire_lease(lease_key, **kwargs)

    def release_lease(self, lease_key: str, **kwargs: Any) -> dict[str, Any]:
        with canonical_mutation_scope(self.actor_id, "lease.release"):
            return self.store.release_lease(lease_key, **kwargs)

    def run_sanitized(self, operation: str, func: Callable[..., Any], /, *args: Any, actor_id: str | None = None, **kwargs: Any) -> Any:
        """For repository-level mutations that persist their own tables.

        All keyword payloads are recursively sanitized before the repository sees
        them. Repository mutators are expected to call require_canonical_mutation().
        """
        clean_kwargs, _ = self._sanitize_mapping(kwargs)
        actor = actor_id or self.actor_id
        with canonical_mutation_scope(actor, operation):
            return func(*args, **clean_kwargs)
