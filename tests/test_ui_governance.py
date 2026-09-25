from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from memory_permanent.api import app, purge_disabled
from memory_permanent.client_auth import required_permission_for_path
from memory_permanent.domain import LifecycleState, map_operator_class
from memory_permanent.ui_governance import (
    p0_ui_b_activation_eligible,
    ui_governance_spec,
)


def test_ui_governance_contract_is_non_destructive_until_m12() -> None:
    spec = ui_governance_spec(gate_status="PENDING")
    assert spec["version"] == "UI-GOV-1.1.0"
    assert spec["active_mode"] == "P0-UI-A"
    assert spec["p0_ui_a"]["enabled"] is True
    assert spec["p0_ui_a"]["destructive"] is False
    assert spec["p0_ui_b"]["enabled"] is False
    assert spec["p0_ui_b"]["activation_gate"] == "M12"
    assert spec["direct_purge_enabled"] is False
    assert spec["physical_delete_from_ui"] is False
    assert spec["classification_contract"]["DESCARTÁVEL"] == "DELETE_ELIGIBLE"
    assert spec["classification_contract"]["DELETE_ELIGIBLE_IS_PHYSICAL_DELETE"] is False


def test_ui_b_becomes_only_governed_request_mode_after_m12() -> None:
    spec = ui_governance_spec(gate_status="PROVEN")
    assert spec["active_mode"] == "P0-UI-B"
    assert spec["p0_ui_b"]["enabled"] is True
    assert spec["p0_ui_b"]["activation_eligible"] is True
    assert "REQUEST_GOVERNED_PURGE" in spec["p0_ui_b"]["allowed_actions"]
    assert spec["direct_purge_enabled"] is False
    assert spec["physical_delete_from_ui"] is False
    assert spec["governed_lifecycle_required"] is True


def test_p0_ui_b_activation_requires_every_m12_proof() -> None:
    assert not p0_ui_b_activation_eligible(
        m12_proven=False,
        lifecycle_manager_proven=True,
        authorized_purge_policy=True,
        recovery_proof_pass=True,
        audit_proof_pass=True,
    )
    assert not p0_ui_b_activation_eligible(
        m12_proven=True,
        lifecycle_manager_proven=False,
        authorized_purge_policy=True,
        recovery_proof_pass=True,
        audit_proof_pass=True,
    )
    assert p0_ui_b_activation_eligible(
        m12_proven=True,
        lifecycle_manager_proven=True,
        authorized_purge_policy=True,
        recovery_proof_pass=True,
        audit_proof_pass=True,
        irreversibility_proof_pass=True,
        separation_of_duties_proven=True,
    )


def test_discardable_is_only_delete_eligible_and_never_purge_allowed() -> None:
    decision = map_operator_class("DESCARTÁVEL")
    assert decision.lifecycle_state is LifecycleState.DELETE_ELIGIBLE
    assert decision.purge_allowed is False


def test_api_contract_exposes_governance_and_blocks_direct_purge() -> None:
    assert app.version == "0.31.0"
    assert "/v1/ui-governance/spec" in app.openapi()["paths"]
    assert required_permission_for_path("/v1/ui-governance/spec", "GET") == "memory:read"
    assert ui_governance_spec(gate_status="PENDING")["p0_ui_b"]["enabled"] is False
    with pytest.raises(HTTPException) as exc:
        purge_disabled()
    assert exc.value.status_code == 405
    assert "M12" in str(exc.value.detail)
    assert "DELETE_ELIGIBLE" in str(exc.value.detail)


def test_panel_has_no_physical_delete_action_and_displays_m12_lock() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "src" / "memory_permanent" / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "src" / "memory_permanent" / "static" / "app.js").read_text(encoding="utf-8")
    assert "P0-UI-B bloqueado até M12" in html
    assert "DELETE_ELIGIBLE" in html
    assert "'/v1/ui-governance/spec'" in js
    assert "method:'DELETE'" not in js
    assert 'method: "DELETE"' not in js
    assert "/v1/purge" not in js


def test_openapi_has_no_delete_method() -> None:
    paths = app.openapi()["paths"]
    assert all("delete" not in methods for methods in paths.values())
