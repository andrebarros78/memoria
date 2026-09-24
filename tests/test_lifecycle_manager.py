from __future__ import annotations

import pytest

from memory_permanent.api import app
from memory_permanent.canonical_mutation import CanonicalMutationRequired
from memory_permanent.client_auth import required_permission_for_path
from memory_permanent.lifecycle_manager import (
    GATE_M12_VERSION,
    LIFECYCLE_MANAGER_VERSION,
    LIFECYCLE_POLICY_VERSION,
    RECOVERY_CONTRACT_VERSION,
    LifecycleManager,
    lifecycle_spec,
    validate_recovery_window,
)


class _NoConnectionStore:
    tenant_id = "LEGACY"


def test_lifecycle_spec_contract_and_m12_transition() -> None:
    pending = lifecycle_spec(gate_status="PENDING")
    assert pending["manager_version"] == LIFECYCLE_MANAGER_VERSION == "LCM-1.0.0"
    assert pending["policy_version"] == LIFECYCLE_POLICY_VERSION == "LCP-1.0.0"
    assert pending["recovery_contract_version"] == RECOVERY_CONTRACT_VERSION == "LRC-1.0.0"
    assert pending["gate"]["version"] == GATE_M12_VERSION == "M12-1.0.0"
    assert pending["gate"]["proven"] is False
    assert pending["p0_ui_b"]["activation_allowed"] is False
    proven = lifecycle_spec(gate_status="PROVEN")
    assert proven["gate"]["proven"] is True
    assert proven["p0_ui_b"]["activation_allowed"] is True
    assert proven["p0_ui_b"]["direct_purge_route_stays_disabled"] is True


def test_recovery_window_is_bounded() -> None:
    assert validate_recovery_window(0) == 0
    assert validate_recovery_window(604800) == 604800
    with pytest.raises(ValueError):
        validate_recovery_window(-1)
    with pytest.raises(ValueError):
        validate_recovery_window(604801)


def test_lifecycle_mutators_require_canonical_boundary() -> None:
    manager = LifecycleManager(_NoConnectionStore())
    with pytest.raises(CanonicalMutationRequired):
        manager.create_hold(item_id="mem-x", hold_type="LEGAL_HOLD", reason="proof", actor="tester")
    with pytest.raises(CanonicalMutationRequired):
        manager.request_purge(item_id="mem-x", reason="proof", recovery_window_seconds=1, evidence={}, actor="tester")


def test_lifecycle_auth_permissions_are_separated() -> None:
    assert required_permission_for_path("/v1/lifecycle/spec", "GET") == "memory:read"
    assert required_permission_for_path("/v1/lifecycle/m12", "GET") == "memory:read"
    assert required_permission_for_path("/v1/lifecycle/requests/lcr-x", "GET") == "memory:read"
    assert required_permission_for_path("/v1/lifecycle/requests", "POST") == "memory:lifecycle"
    assert required_permission_for_path("/v1/lifecycle/holds", "POST") == "memory:lifecycle"
    assert required_permission_for_path("/v1/lifecycle/requests/lcr-x/quarantine", "POST") == "memory:lifecycle"
    assert required_permission_for_path("/v1/lifecycle/requests/lcr-x/recover", "POST") == "memory:lifecycle"
    assert required_permission_for_path("/v1/lifecycle/requests/lcr-x/approve", "POST") == "memory:purge"
    assert required_permission_for_path("/v1/lifecycle/requests/lcr-x/purge", "POST") == "memory:purge"
    assert required_permission_for_path("/v1/lifecycle/requests/lcr-x/finalize", "POST") == "memory:purge"
    assert required_permission_for_path("/v1/lifecycle/m12/close", "POST") == "memory:purge"


def test_openapi_exposes_governed_workflow_but_no_delete_method() -> None:
    paths = app.openapi()["paths"]
    for path in (
        "/v1/lifecycle/spec",
        "/v1/lifecycle/m12",
        "/v1/lifecycle/m12/close",
        "/v1/lifecycle/holds",
        "/v1/lifecycle/holds/{hold_id}/release",
        "/v1/lifecycle/requests",
        "/v1/lifecycle/requests/{request_id}",
        "/v1/lifecycle/requests/{request_id}/quarantine",
        "/v1/lifecycle/requests/{request_id}/approve",
        "/v1/lifecycle/requests/{request_id}/purge",
        "/v1/lifecycle/requests/{request_id}/recover",
        "/v1/lifecycle/requests/{request_id}/finalize",
    ):
        assert path in paths
    assert all("delete" not in methods for methods in paths.values())
    assert app.version == "0.29.3"
