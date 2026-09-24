from __future__ import annotations

import ast
from pathlib import Path


def test_dynamic_query_clause_fragments_are_code_literals_only():
    path = Path(__file__).resolve().parents[1] / "src" / "memory_permanent" / "store.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    guarded_names = {"clauses", "state_clauses", "result_clauses"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append":
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id in guarded_names:
                assert len(node.args) == 1
                assert isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str), (
                    f"dynamic SQL clause for {owner.id} must be a code literal at line {node.lineno}"
                )
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "clause":
            assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str), (
                f"dynamic SQL clause extension must be a code literal at line {node.lineno}"
            )
