from __future__ import annotations

from enum import StrEnum
from typing import Any

MEMORY_SCOPE_VERSION = "MS-1.0.0"


class MemoryScope(StrEnum):
    GLOBAL_USER = "GLOBAL_USER"
    PROJECT = "PROJECT"
    MISSION = "MISSION"
    SESSION = "SESSION"


HUMAN_LABELS: dict[MemoryScope, str] = {
    MemoryScope.GLOBAL_USER: "Memória Geral",
    MemoryScope.PROJECT: "Projeto",
    MemoryScope.MISSION: "Missão",
    MemoryScope.SESSION: "Sessão",
}


def normalize_memory_scope(scope: str | MemoryScope | None, scope_ref: str | None = None) -> tuple[MemoryScope, str | None]:
    raw = str(scope or MemoryScope.GLOBAL_USER.value).strip().upper()
    try:
        value = MemoryScope(raw)
    except ValueError as exc:
        raise ValueError("invalid memory_scope") from exc
    ref = str(scope_ref or "").strip() or None
    if ref is not None and len(ref) > 240:
        raise ValueError("memory_scope_ref too long")
    if value is MemoryScope.GLOBAL_USER:
        if ref is not None:
            raise ValueError("GLOBAL_USER memory_scope must not have memory_scope_ref")
        return value, None
    if ref is None:
        raise ValueError(f"{value.value} memory_scope requires memory_scope_ref")
    return value, ref


def memory_scope_spec() -> dict[str, Any]:
    return {
        "version": MEMORY_SCOPE_VERSION,
        "scopes": [scope.value for scope in MemoryScope],
        "human_labels": {scope.value: HUMAN_LABELS[scope] for scope in MemoryScope},
        "canonical_global_scope": MemoryScope.GLOBAL_USER.value,
        "general_memory_human_label": HUMAN_LABELS[MemoryScope.GLOBAL_USER],
        "separation": {
            "memory_scope": "SEMANTIC_CONTEXT",
            "sharing_scope": "ACCESS_CONTROL",
            "memory_scope_is_acl": False,
        },
        "reference_rules": {
            MemoryScope.GLOBAL_USER.value: "NO_REFERENCE",
            MemoryScope.PROJECT.value: "PROJECT_ID_REFERENCE_REQUIRED",
            MemoryScope.MISSION.value: "MISSION_ID_REFERENCE_REQUIRED",
            MemoryScope.SESSION.value: "SESSION_ID_REFERENCE_REQUIRED",
        },
    }
