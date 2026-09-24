from __future__ import annotations

UI_GOVERNANCE_VERSION = "UI-GOV-1.1.0"
P0_UI_A = "P0-UI-A"
P0_UI_B = "P0-UI-B"
M12_GATE = "M12"


def ui_governance_spec(*, gate_status: str = "PENDING") -> dict[str, object]:
    m12_proven = str(gate_status or "PENDING").strip().upper() == "PROVEN"
    return {
        "version": UI_GOVERNANCE_VERSION,
        "active_mode": P0_UI_B if m12_proven else P0_UI_A,
        "p0_ui_a": {
            "enabled": True,
            "destructive": False,
            "allowed_actions": [
                "READ",
                "FILTER",
                "CLASSIFY",
                "MARK_DELETE_ELIGIBLE",
                "EXPORT_REPORT",
            ],
        },
        "p0_ui_b": {
            "enabled": m12_proven,
            "activation_eligible": m12_proven,
            "destructive": True,
            "activation_gate": M12_GATE,
            "activation_condition": "M12_PROVEN",
            "allowed_actions": ["REQUEST_GOVERNED_PURGE", "VIEW_LIFECYCLE_STATUS"] if m12_proven else [],
            "required_proofs": [
                "LIFECYCLE_MANAGER_PROVEN",
                "AUTHORIZED_PURGE_POLICY",
                "SEPARATION_OF_DUTIES_PROVEN",
                "ROUNDTRIP_RECOVERY_PROOF_PASS",
                "IRREVERSIBILITY_PROOF_PASS",
                "AUDIT_PROOF_PASS",
            ],
        },
        "classification_contract": {
            "DESCARTÁVEL": "DELETE_ELIGIBLE",
            "DELETE_ELIGIBLE_IS_PHYSICAL_DELETE": False,
        },
        "direct_purge_enabled": False,
        "direct_purge_route_behavior": "BLOCKED_405",
        "physical_delete_from_ui": False,
        "governed_lifecycle_required": True,
        "next_gate": None if m12_proven else M12_GATE,
    }


def p0_ui_b_activation_eligible(
    *,
    m12_proven: bool,
    lifecycle_manager_proven: bool,
    authorized_purge_policy: bool,
    recovery_proof_pass: bool,
    audit_proof_pass: bool,
    irreversibility_proof_pass: bool = True,
    separation_of_duties_proven: bool = True,
) -> bool:
    return all(
        (
            m12_proven,
            lifecycle_manager_proven,
            authorized_purge_policy,
            recovery_proof_pass,
            audit_proof_pass,
            irreversibility_proof_pass,
            separation_of_duties_proven,
        )
    )
