import pytest

from memory_permanent.provider_adapter import (
    OllamaProviderAdapter,
    OpenAIProviderAdapter,
)


def test_ollama_json_extraction_accepts_plain_json():
    value = OllamaProviderAdapter._extract_json('{"context_sha256":"abc","checkpoint_id":"cp","required_memory_ids":[],"objective":"x"}')
    assert value["checkpoint_id"] == "cp"


def test_openai_paid_inference_is_fail_closed(monkeypatch):
    monkeypatch.delenv("MEMORY_ALLOW_PAID_PROVIDER_PROOF", raising=False)
    adapter = OpenAIProviderAdapter(api_key="configured-for-test")
    with pytest.raises(PermissionError):
        adapter.observe_context({"context": {}})

class _FakeOpenAI(OpenAIProviderAdapter):
    def _request(self, method, path, payload=None, timeout=30.0):
        assert method == "POST"
        assert path == "/responses"
        assert payload["model"] == "gpt-5.6-luna"
        return {
            "id": "resp-test-m6",
            "status": "completed",
            "output": [{"type":"message","content":[{"type":"output_text","text":"{\"context_sha256\":\"hash-1\",\"checkpoint_id\":\"cp-1\",\"required_memory_ids\":[\"mem-1\"],\"objective\":\"finish-v4\"}"}]}],
            "usage": {"input_tokens": 40, "output_tokens": 30},
        }


def test_openai_responses_adapter_preserves_same_context(monkeypatch):
    monkeypatch.setenv("MEMORY_ALLOW_PAID_PROVIDER_PROOF", "1")
    adapter = _FakeOpenAI(api_key="configured-for-test")
    obs = adapter.observe_context({
        "context_sha256": "hash-1",
        "checkpoint_id": "cp-1",
        "required_memory_ids": ["mem-1"],
        "context": {"objective": "finish-v4"},
    })
    assert obs.provider == "openai"
    assert obs.model == "gpt-5.6-luna"
    assert obs.context_sha256 == "hash-1"
    assert obs.checkpoint_id == "cp-1"
    assert obs.required_memory_ids == ["mem-1"]
    assert obs.objective == "finish-v4"
    assert obs.metadata["paid_inference_used"] is True
