from __future__ import annotations

import pytest

from memory_permanent.access_policy import AgentAccessContext
from memory_permanent.api import app
from memory_permanent.memory_scope import (
    MEMORY_SCOPE_VERSION,
    MemoryScope,
    memory_scope_spec,
    normalize_memory_scope,
)


def test_exact_canonical_memory_scopes_and_general_label() -> None:
    assert [x.value for x in MemoryScope] == ["GLOBAL_USER", "PROJECT", "MISSION", "SESSION"]
    spec = memory_scope_spec()
    assert spec["version"] == MEMORY_SCOPE_VERSION == "MS-1.0.0"
    assert spec["canonical_global_scope"] == "GLOBAL_USER"
    assert spec["general_memory_human_label"] == "Memória Geral"
    assert spec["separation"]["memory_scope_is_acl"] is False


def test_global_user_has_no_reference_and_contextual_scopes_require_one() -> None:
    scope, ref = normalize_memory_scope("GLOBAL_USER")
    assert (scope.value, ref) == ("GLOBAL_USER", None)
    with pytest.raises(ValueError, match="must not have"):
        normalize_memory_scope("GLOBAL_USER", "project-x")
    for kind in ("PROJECT", "MISSION", "SESSION"):
        with pytest.raises(ValueError, match="requires memory_scope_ref"):
            normalize_memory_scope(kind)
        resolved, resolved_ref = normalize_memory_scope(kind, f"{kind.lower()}-1")
        assert resolved.value == kind
        assert resolved_ref == f"{kind.lower()}-1"


def test_semantic_and_acl_codes_are_not_interchangeable() -> None:
    ctx = AgentAccessContext.system()
    assert ctx.validate_memory_scope("GLOBAL_USER") == {"memory_scope": "GLOBAL_USER", "memory_scope_ref": None}
    assert ctx.validate_sharing_scope("SYSTEM_SHARED")["sharing_scope"] == "SYSTEM_SHARED"
    with pytest.raises(ValueError, match="sharing_scope"):
        ctx.validate_sharing_scope("GLOBAL_USER")
    with pytest.raises(ValueError, match="memory_scope"):
        ctx.validate_memory_scope("SYSTEM_SHARED")


def test_project_semantic_scope_is_independent_from_project_sharing_acl() -> None:
    ctx = AgentAccessContext.build(agent_id="agent-a", project_id="project-acl")
    semantic = ctx.validate_memory_scope("PROJECT", memory_scope_ref="project-semantic")
    sharing = ctx.validate_sharing_scope("PROJECT_SHARED", project_id="project-acl")
    assert semantic == {"memory_scope": "PROJECT", "memory_scope_ref": "project-semantic"}
    assert sharing["project_id"] == "project-acl"


def test_api_contract_exposes_memory_scope_and_scope_spec() -> None:
    schema = app.openapi()
    assert "/v1/memory-scopes" in schema["paths"]
    remember = schema["components"]["schemas"]["RememberRequest"]["properties"]
    assert remember["memory_scope"]["$ref"].endswith("/MemoryScope")
    enum = schema["components"]["schemas"]["MemoryScope"]["enum"]
    assert enum == ["GLOBAL_USER", "PROJECT", "MISSION", "SESSION"]
    assert remember["memory_scope"]["default"] == "GLOBAL_USER"
    assert "sharing_scope" in remember
