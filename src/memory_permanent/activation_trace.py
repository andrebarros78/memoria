from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True)
class ActivationTrace:
    memory_id: str
    activation_level: float
    components: Mapping[str, float]
    policy_version: str
    trace_id: str | None = None
    mode: str = "SHADOW"
    truth_mutated: bool = False
    promotion_performed: bool = False
    computed_at: datetime = datetime.min.replace(tzinfo=UTC)

    def __post_init__(self) -> None:
        if not self.memory_id.strip():
            raise ValueError("memory_id is required")
        if not 0.0 <= float(self.activation_level) <= 1.0:
            raise ValueError("activation_level must be between 0 and 1")
        if self.computed_at == datetime.min.replace(tzinfo=UTC):
            object.__setattr__(self, "computed_at", datetime.now(UTC))
        if self.computed_at.tzinfo is None:
            raise ValueError("computed_at must be timezone-aware")
        object.__setattr__(self, "components", MappingProxyType({str(k): float(v) for k, v in self.components.items()}))

    def as_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "activation_level": self.activation_level,
            "components": dict(self.components),
            "policy_version": self.policy_version,
            "trace_id": self.trace_id,
            "mode": self.mode,
            "truth_mutated": self.truth_mutated,
            "promotion_performed": self.promotion_performed,
            "computed_at": self.computed_at.isoformat(),
        }
