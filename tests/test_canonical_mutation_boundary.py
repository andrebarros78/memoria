from __future__ import annotations

import ast
from pathlib import Path

import pytest

from memory_permanent.canonical_mutation import CanonicalMutationRequired
from memory_permanent.store import PostgresMemoryStore

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "memory_permanent"

PROTECTED_STORE_CALLS = {
    "remember", "revise", "validate_current_version", "record_application", "record_outcome",
    "save_checkpoint", "record_retrieval_trace", "store_embedding", "mark_embedding_failed",
    "classify", "acquire_lease", "release_lease", "reseal_audit_chain",
    "create_retrieval_golden_set", "record_retrieval_quality_run",
}

REPO_GUARDS = {
    "session_rotation.py": {
        "create_session", "create_binding", "capture_external_conversation", "request_rotation",
        "update_safe_point", "prepare_rotation", "bind_new_external", "validate_rotation",
        "complete_rotation", "abort_rotation",
    },
    "conversation_ingestion.py": {"enqueue_turn", "_persist_turn", "process_event", "retry_pending"},
}


def test_direct_store_mutation_fails_closed() -> None:
    store = object.__new__(PostgresMemoryStore)
    with pytest.raises(CanonicalMutationRequired):
        store.classify([], "ATIVA", changed_by="bypass")


def test_no_protected_store_mutator_calls_outside_canonical_service() -> None:
    violations: list[str] = []
    for path in SRC.glob("*.py"):
        if path.name in {"canonical_mutation.py", "store.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in PROTECTED_STORE_CALLS:
                continue
            base = node.func.value
            if isinstance(base, ast.Attribute) and base.attr == "store":
                violations.append(f"{path.name}:{node.lineno}:{node.func.attr}")
    assert violations == []


def test_repository_mutators_require_canonical_context() -> None:
    missing: list[str] = []
    for filename, methods in REPO_GUARDS.items():
        path = SRC / filename
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        found = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in methods}
        for name in methods:
            node = found.get(name)
            if node is None or not node.body:
                missing.append(f"{filename}:{name}:missing")
                continue
            first = node.body[0]
            ok = (
                isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
                and getattr(first.value.func, "id", None) == "require_canonical_mutation"
            )
            if not ok:
                missing.append(f"{filename}:{name}:unguarded")
    assert missing == []
