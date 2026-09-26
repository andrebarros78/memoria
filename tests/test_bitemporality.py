from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from memory_permanent.api import app
from memory_permanent.context_engine import ContextEngine
from memory_permanent.temporal import (
    BITEMPORAL_VERSION,
    normalize_temporal_envelope,
    temporal_spec,
)


def test_late_event_preserves_fact_and_knowledge_time() -> None:
    occurred = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    observed = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    env = normalize_temporal_envelope(occurred_at=occurred, observed_at=observed)
    assert env.occurred_at == occurred
    assert env.observed_at == observed
    assert env.valid_from == occurred
    assert env.valid_to is None
    assert env.late_arrival is True


def test_temporal_envelope_rejects_ambiguous_or_impossible_time() -> None:
    with pytest.raises(ValueError, match="timezone"):
        normalize_temporal_envelope(occurred_at=datetime(2026, 8, 1, 10, 0))
    occurred = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="observed_at"):
        normalize_temporal_envelope(occurred_at=occurred, observed_at=occurred - timedelta(seconds=1))
    with pytest.raises(ValueError, match="valid_to"):
        normalize_temporal_envelope(occurred_at=occurred, valid_from=occurred, valid_to=occurred)


def test_temporal_spec_is_explicit_and_not_created_at_validity() -> None:
    spec = temporal_spec()
    assert spec["version"] == BITEMPORAL_VERSION == "BT-1.0.0"
    assert spec["dimensions"]["occurred_at"] == "REAL_WORLD_FACT_TIME"
    assert spec["dimensions"]["observed_at"] == "KNOWLEDGE_TIME"
    assert spec["dimensions"]["created_at"] == "PERSISTENCE_TIME_IMMUTABLE"
    assert spec["validity_rule"] == "created_at is never used as valid_from"


def test_temporal_spec_is_public_api_contract_but_requires_auth_runtime() -> None:
    paths = app.openapi()["paths"]
    assert "/v1/temporal-spec" in paths
    assert app.version == "0.32.0"


class _AsOfStore:
    def __init__(self) -> None:
        self.lexical = None
        self.checkpoint = None

    def memory_candidates(self, query, namespaces, limit, **kwargs):
        self.lexical = kwargs
        return []

    def semantic_candidates(self, namespaces, model_id, **kwargs):
        return []

    def latest_checkpoint(self, mission_id, namespaces, **kwargs):
        self.checkpoint = kwargs

    def record_retrieval_trace(self, *args, **kwargs):
        return "trace-test"


def test_context_engine_forwards_bitemporal_as_of_selectors() -> None:
    store = _AsOfStore()
    valid_at = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    known_at = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    ContextEngine(store).retrieve(
        "temporal", namespaces=("PROOF",), mission_id="mission-1",
        valid_at=valid_at, known_at=known_at,
    )
    assert store.lexical == {
        "mission_id": "mission-1", "session_id": None,
        "valid_at": valid_at, "known_at": known_at,
    }
    assert store.checkpoint == {"valid_at": valid_at, "known_at": known_at}
