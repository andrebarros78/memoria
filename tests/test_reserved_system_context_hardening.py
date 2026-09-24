from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from memory_permanent.client_auth import ClientPrincipal

ROOT = Path(__file__).resolve().parents[1]


def _principal(*, tenants: frozenset[str], agents: frozenset[str] = frozenset()) -> ClientPrincipal:
    return ClientPrincipal(
        client_id="audit-client",
        permissions=frozenset({"memory:read"}),
        tenants=tenants,
        agents=agents,
        users=frozenset(),
        projects=frozenset(),
        teams=frozenset(),
        organizations=frozenset(),
    )


def test_api_clients_cannot_claim_reserved_system_tenant() -> None:
    principal = _principal(tenants=frozenset({"__SYSTEM__"}))
    with pytest.raises(HTTPException) as exc:
        principal.resolve_claims(
            tenant="__SYSTEM__", agent=None, user=None, project=None, team=None, organization=None
        )
    assert exc.value.status_code == 403


def test_api_clients_cannot_claim_reserved_system_agent() -> None:
    principal = _principal(tenants=frozenset({"TENANT_A"}), agents=frozenset({"__SYSTEM__"}))
    with pytest.raises(HTTPException) as exc:
        principal.resolve_claims(
            tenant="TENANT_A", agent="__SYSTEM__", user=None, project=None, team=None, organization=None
        )
    assert exc.value.status_code == 403


def test_migration_0051_blocks_runtime_system_bypass_and_superuser_gate() -> None:
    sql = (ROOT / "migrations" / "0051_reserved_system_and_restore_gate_hardening.sql").read_text(encoding="utf-8")
    assert "current_user <> 'memory_app'" in sql
    assert "current_user = 'memory_app'" in sql
    assert "runtime role cannot use reserved system tenant context" in sql
    assert "restore replay gate is administrative-only" in sql
    assert "VALUES('restore_erasure_replay_status','PENDING')" in sql
    assert "OWNER TO memory_admin" in sql


def test_runtime_replay_cannot_open_restore_gate() -> None:
    source = (ROOT / "src" / "memory_permanent" / "erasure_manager.py").read_text(encoding="utf-8")
    replay_body = source.split("def replay(", 1)[1].split("def get_erasure(", 1)[0]
    assert "restore_erasure_replay_status" not in replay_body


def test_restore_proof_forces_pending_then_admin_pass_after_replay() -> None:
    source = (ROOT / "scripts" / "prove_v52_encrypted_restore.py").read_text(encoding="utf-8")
    pending = source.index("VALUES('restore_erasure_replay_status','PENDING')")
    replay = source.index("replay=ErasureManager(store).replay")
    passed = source.index("VALUES('restore_erasure_replay_status','PASS')")
    assert pending < replay < passed
    assert 'os.environ["PGPASSFILE"]=str(admin_pass)' in source


def test_obsolete_restore_gate_patch_helper_is_removed() -> None:
    assert not (ROOT / "scripts" / "patch_restore_gate.py").exists()