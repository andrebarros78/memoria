from __future__ import annotations

from typing import Any

from .client_auth import ClientPrincipal

TRUST_ASSIGNER = "memory-api-identity"


def derive_authenticated_provenance(
    principal: ClientPrincipal,
    *,
    asserted_source: str,
    asserted_provenance: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    """Convert caller assertions into authenticated provenance.

    Caller supplied source/trusted values are evidence only. They never become
    authority by themselves. Trust is assigned exclusively from authenticated
    capabilities.
    """
    asserted = dict(asserted_provenance or {})
    asserted.pop("trusted", None)
    asserted.pop("trust", None)
    asserted.pop("trust_assigned_by", None)

    trusted = "provenance:attest" in principal.permissions
    provenance = {
        "trusted": trusted,
        "trust_assigned_by": TRUST_ASSIGNER,
        "authenticated_client_id": principal.client_id,
        "trust": {
            "trusted": trusted,
            "basis": "AUTHENTICATED_CAPABILITY" if trusted else "AUTHENTICATED_IDENTITY_UNATTESTED",
            "capability": "provenance:attest" if trusted else None,
        },
        "asserted_source": str(asserted_source or "unknown"),
        "asserted_provenance": asserted,
    }
    source = f"authenticated-client:{principal.client_id}"
    return source, provenance


def is_system_assigned_trust(provenance: dict[str, Any] | None) -> bool:
    data = dict(provenance or {})
    trust_value = data.get("trust")
    trust: dict[str, Any] = trust_value if isinstance(trust_value, dict) else {}
    return (
        data.get("trust_assigned_by") in {TRUST_ASSIGNER, "internal-system", "migration-attested"}
        and bool(trust.get("trusted", data.get("trusted", False)))
    )
