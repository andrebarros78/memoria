from __future__ import annotations

from memory_permanent.context_engine import ContextEngine


class _BaseStore:
    tenant_id = "TENANT-A"

    def __init__(self) -> None:
        self.trace_calls = 0

    def memory_candidates(self, query, namespaces, limit, **kwargs):
        return [
            {
                "item_id": "mem-high",
                "namespace": namespaces[0],
                "memory_key": "high",
                "content_sha256": "a" * 64,
                "confidence": 0.9,
                "source": "test",
                "operator_class": "ATIVA",
                "lifecycle_state": "HOT",
                "text_rank": 0.9,
                "exact_substring_match": True,
                "created_at": "2026-09-24T19:00:00+00:00",
            },
            {
                "item_id": "mem-low",
                "namespace": namespaces[0],
                "memory_key": "low",
                "content_sha256": "b" * 64,
                "confidence": 0.2,
                "source": "test",
                "operator_class": "ATIVA",
                "lifecycle_state": "HOT",
                "text_rank": 0.1,
                "exact_substring_match": False,
                "created_at": "2026-09-24T19:00:00+00:00",
            },
        ]

    def record_retrieval_trace(self, query, namespaces, candidates, selected, conflicts, **kwargs):
        self.trace_calls += 1
        return "trace-f02"

    def latest_checkpoint(self, mission_id, namespaces, **kwargs):
        return None


class _Observer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = []

    def observe_retrieval(self, *, selected, trace_id):
        self.calls.append((selected, trace_id))
        if self.fail:
            raise RuntimeError("simulated cognitive engine failure")


def test_phase2_shadow_hook_observes_after_base_ranking_without_reranking():
    store = _BaseStore()
    observer = _Observer()
    engine = ContextEngine(store, cognitive_observer=observer)
    result = engine.retrieve("high", namespaces=("TEST",), limit=2)
    assert [item["item_id"] for item in result.selected] == ["mem-high", "mem-low"]
    assert observer.calls[0][1] == "trace-f02"
    assert [item["item_id"] for item in observer.calls[0][0]] == ["mem-high", "mem-low"]


def test_phase2_cognitive_failure_does_not_break_base_retrieval():
    store = _BaseStore()
    observer = _Observer(fail=True)
    engine = ContextEngine(store, cognitive_observer=observer)
    result = engine.retrieve("high", namespaces=("TEST",), limit=2)
    assert result.trace_id == "trace-f02"
    assert result.selected[0]["item_id"] == "mem-high"
    assert store.trace_calls == 1
