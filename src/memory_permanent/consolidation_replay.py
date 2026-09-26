from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

CONSOLIDATION_REPLAY_VERSION = "CRP-1.0.0"


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConsolidationSourceSnapshot:
    memory_id: str
    namespace: str
    category: str
    content_sha256: str
    confidence: float
    salience: float
    activation: float
    outcome_signal: float
    association_signal: float
    conflict: bool = False

    def __post_init__(self) -> None:
        for name in ("memory_id", "namespace", "category", "content_sha256"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value)
        if len(self.content_sha256) != 64 or any(char not in "0123456789abcdef" for char in self.content_sha256.lower()):
            raise ValueError("content_sha256 must be a lowercase SHA-256 hex digest")
        object.__setattr__(self, "content_sha256", self.content_sha256.lower())
        for name in ("confidence", "salience", "activation", "outcome_signal", "association_signal"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} out of bounds")
            object.__setattr__(self, name, value)

    def proof_ref(self) -> str:
        return f"memory:{self.memory_id}:{self.content_sha256}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "namespace": self.namespace,
            "category": self.category,
            "content_sha256": self.content_sha256,
            "confidence": self.confidence,
            "salience": self.salience,
            "activation": self.activation,
            "outcome_signal": self.outcome_signal,
            "association_signal": self.association_signal,
            "conflict": self.conflict,
        }


@dataclass(frozen=True, slots=True)
class ConsolidationReplay:
    source_ids: tuple[str, ...]
    source_digest: str
    replay_digest: str
    cluster_keys: tuple[str, ...]
    trace: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace", MappingProxyType(dict(self.trace)))


def build_replay(sources: Sequence[ConsolidationSourceSnapshot]) -> ConsolidationReplay:
    ordered = tuple(sorted(sources, key=lambda source: (source.namespace, source.category, source.memory_id)))
    source_material = [source.as_dict() for source in ordered]
    source_digest = _sha(source_material)
    cluster_keys = tuple(sorted({f"{source.namespace}:{source.category}" for source in ordered}))
    replay_material = {
        "version": CONSOLIDATION_REPLAY_VERSION,
        "source_digest": source_digest,
        "source_ids": [source.memory_id for source in ordered],
        "cluster_keys": list(cluster_keys),
    }
    replay_digest = _sha(replay_material)
    return ConsolidationReplay(
        source_ids=tuple(source.memory_id for source in ordered),
        source_digest=source_digest,
        replay_digest=replay_digest,
        cluster_keys=cluster_keys,
        trace={
            "version": CONSOLIDATION_REPLAY_VERSION,
            "source_count": len(ordered),
            "source_digest": source_digest,
            "replay_digest": replay_digest,
            "cluster_keys": cluster_keys,
            "contains_memory_content": False,
            "deterministic": True,
        },
    )


def replay_matches(
    sources: Sequence[ConsolidationSourceSnapshot],
    *,
    expected_source_digest: str,
    expected_replay_digest: str,
) -> bool:
    replay = build_replay(sources)
    return replay.source_digest == str(expected_source_digest) and replay.replay_digest == str(expected_replay_digest)
