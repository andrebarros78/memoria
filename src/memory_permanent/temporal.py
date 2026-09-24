from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

BITEMPORAL_VERSION = "BT-1.0.0"


def _aware(value: datetime | None, name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include timezone")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class TemporalEnvelope:
    occurred_at: datetime
    observed_at: datetime
    valid_from: datetime
    valid_to: datetime | None

    @property
    def late_arrival(self) -> bool:
        return self.observed_at > self.occurred_at

    def as_dict(self) -> dict[str, Any]:
        return {
            "occurred_at": self.occurred_at.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "late_arrival": self.late_arrival,
            "version": BITEMPORAL_VERSION,
        }


def normalize_temporal_envelope(
    *,
    occurred_at: datetime | None = None,
    observed_at: datetime | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    now: datetime | None = None,
) -> TemporalEnvelope:
    clock = datetime.now(UTC)
    if now is not None:
        normalized_now = _aware(now, "now")
        if normalized_now is None:
            raise RuntimeError("normalized clock cannot be None")
        clock = normalized_now
    occurred_candidate = _aware(occurred_at, "occurred_at")
    occurred = clock if occurred_candidate is None else occurred_candidate
    observed_candidate = _aware(observed_at, "observed_at")
    observed = clock if observed_candidate is None else observed_candidate
    effective_from_candidate = _aware(valid_from, "valid_from")
    effective_from = occurred if effective_from_candidate is None else effective_from_candidate
    effective_to = _aware(valid_to, "valid_to")
    if observed < occurred:
        raise ValueError("observed_at cannot precede occurred_at")
    if effective_to is not None and effective_to <= effective_from:
        raise ValueError("valid_to must be greater than valid_from")
    return TemporalEnvelope(occurred, observed, effective_from, effective_to)


def temporal_spec() -> dict[str, Any]:
    return {
        "version": BITEMPORAL_VERSION,
        "dimensions": {
            "occurred_at": "REAL_WORLD_FACT_TIME",
            "observed_at": "KNOWLEDGE_TIME",
            "valid_from": "EFFECTIVE_VALIDITY_START",
            "valid_to": "EFFECTIVE_VALIDITY_END_EXCLUSIVE",
            "created_at": "PERSISTENCE_TIME_IMMUTABLE",
        },
        "ordering": ["occurred_at", "observed_at", "created_at"],
        "constraints": [
            "observed_at >= occurred_at",
            "valid_to IS NULL OR valid_to > valid_from",
        ],
        "late_event_rule": "occurred_at < observed_at; created_at remains independent persistence time",
        "validity_rule": "created_at is never used as valid_from",
    }


def normalize_as_of(value: datetime | None, name: str) -> datetime:
    if value is None:
        return datetime.now(UTC)
    normalized = _aware(value, name)
    if normalized is None:
        raise ValueError(f"{name} must not be null")
    return normalized
