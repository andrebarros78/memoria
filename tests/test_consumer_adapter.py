import inspect

import pytest

from memory_permanent.consumer_adapter import (
    UniversalMemoryClientAdapter,
    consumer_adapter_spec,
)
from memory_permanent.signed_client import SignedMemoryClient


class FakeTransport:
    def __init__(self):
        self.calls = []

    def request(self, method, path_query, payload=None, extra_headers=None, timeout=30):
        self.calls.append((method, path_query, payload, extra_headers))
        if path_query == "/health":
            return 200, {"status": "ok"}
        if path_query.startswith("/v1/checkpoints/") and path_query.endswith("/latest"):
            return 200, {"checkpoint_id": "cp-1", "state": {"step": 4}}
        if path_query == "/v1/context/retrieve":
            return 200, {"trace_id": "trace-1", "selected": [{"item_id": "mem-1"}]}
        if path_query == "/v1/checkpoints":
            return 201, {"checkpoint_id": "cp-1"}
        if path_query == "/v1/memories":
            return 201, {"item_id": "mem-1"}
        return 404, {"detail": "not found"}


def test_consumer_adapter_is_database_decoupled_and_covers_universal_contract():
    spec = consumer_adapter_spec()
    assert spec["direct_database_access"] is False
    assert spec["database_driver_dependency"] is False
    assert set(spec["operations"]) == {
        "memory.capture",
        "memory.context",
        "memory.search",
        "memory.checkpoint",
        "memory.resume",
        "memory.state",
    }
    source = inspect.getsource(__import__("memory_permanent.consumer_adapter", fromlist=["x"]))
    assert "psycopg" not in source.lower()
    assert "postgresql://" not in source.lower()


def test_consumer_adapter_executes_capture_context_checkpoint_and_resume_via_transport():
    fake = FakeTransport()
    client = UniversalMemoryClientAdapter("https://memory.example.test", "consumer-test", transport=fake)
    assert client.health()["status"] == "ok"
    assert client.capture({"namespace": "TEST"}, project_id="project-a")["item_id"] == "mem-1"
    assert client.context("where are we", ["TEST"], project_id="project-a")["trace_id"] == "trace-1"
    assert client.checkpoint({"namespace": "TEST"}, project_id="project-a")["checkpoint_id"] == "cp-1"
    resumed = client.resume("mission-1", "continue", ["TEST"], project_id="project-a")
    assert resumed["checkpoint"]["checkpoint_id"] == "cp-1"
    assert resumed["context"]["trace_id"] == "trace-1"
    assert resumed["direct_database_access"] is False
    assert all((headers or {}).get("X-Memory-Project") == "project-a" for _, path, _, headers in fake.calls if path != "/health")


def test_signed_client_allows_https_remote_but_forbids_cleartext_remote():
    remote = SignedMemoryClient("https://memory.example.com", "consumer-test")
    assert remote.base_url == "https://memory.example.com"
    local = SignedMemoryClient("http://127.0.0.1:8787", "consumer-test")
    assert local.base_url == "http://127.0.0.1:8787"
    with pytest.raises(ValueError, match="cleartext HTTP"):
        SignedMemoryClient("http://memory.example.com", "consumer-test")
