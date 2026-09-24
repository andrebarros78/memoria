from __future__ import annotations

import importlib.util
from pathlib import Path

from memory_permanent.ai_integration_adapter import ai_integration_spec
from memory_permanent.product_universality import product_universality_spec
from memory_permanent.v55_runtime import v55_runtime_spec


def test_concrete_llm_inference_is_not_part_of_memory_core():
    assert importlib.util.find_spec("memory_permanent.provider_adapter") is None
    spec = v55_runtime_spec()
    assert spec["external_llm_inference_owned_by_core"] is False
    assert {"OPENAI", "OLLAMA", "LLAMA_CPP"}.isdisjoint(spec["official_adapters"])
    assert "external_ai_integration" in spec["capability_profiles"]["AI"]
    assert "provider_adapters" not in spec["capability_profiles"]["AI"]


def test_external_ai_boundary_remains_governed_and_provider_neutral():
    ai = ai_integration_spec()
    product = product_universality_spec()
    assert ai["external_ai_direct_database_access"] is False
    assert ai["external_ai_direct_memory_write"] is False
    assert product["guarantees"]["external_ai_suggests_only"] is True
    assert product["guarantees"]["llm_inference_owned_by_memory_core"] is False


def test_forbidden_concrete_llm_runtime_markers_do_not_reenter_core():
    core = Path(__file__).resolve().parents[1] / "src" / "memory_permanent"
    forbidden = (
        "OPENAI_API_KEY",
        "MEMORY_ALLOW_PAID_PROVIDER_PROOF",
        '"/responses"',
        '"/models"',
        '"/api/generate"',
        '"/api/tags"',
        "127.0.0.1:11434",
        "127.0.0.1:11435",
        "paid_inference_used",
    )
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(core.glob("*.py"))
    )
    for marker in forbidden:
        assert marker not in combined
