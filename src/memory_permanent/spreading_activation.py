from __future__ import annotations

import heapq
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any

from .association_policy import (
    ASSOCIATION_POLICY_VERSION,
    AssociationLimits,
    AssociationRelation,
    evidence_filter,
    normalize_relation,
)


@dataclass(frozen=True, slots=True)
class AssociationNeighbor:
    memory_id: str
    relation_type: AssociationRelation
    weight: float
    evidence_strength: float
    source_kind: str
    source_ref: str
    evidence: dict[str, Any]

    def __post_init__(self) -> None:
        memory_id = str(self.memory_id).strip()
        source_kind = str(self.source_kind).strip().upper()
        source_ref = str(self.source_ref).strip()
        if not memory_id or len(memory_id) > 160:
            raise ValueError("invalid association neighbor memory_id")
        if not source_kind or len(source_kind) > 80:
            raise ValueError("invalid association source_kind")
        if not source_ref or len(source_ref) > 512:
            raise ValueError("invalid association source_ref")
        if not 0.0 <= float(self.weight) <= 1.0:
            raise ValueError("association weight must be in [0, 1]")
        if not 0.0 <= float(self.evidence_strength) <= 1.0:
            raise ValueError("evidence_strength must be in [0, 1]")
        object.__setattr__(self, "memory_id", memory_id)
        object.__setattr__(self, "relation_type", normalize_relation(self.relation_type))
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(self, "evidence", dict(self.evidence or {}))


@dataclass(frozen=True, slots=True)
class AssociationCandidate:
    seed_memory_id: str
    memory_id: str
    relation_type: AssociationRelation
    activation_score: float
    hop_depth: int
    path: tuple[str, ...]
    source_kind: str
    source_ref: str
    evidence_strength: float
    evidence: dict[str, Any]
    conflict: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed_memory_id": self.seed_memory_id,
            "memory_id": self.memory_id,
            "relation_type": self.relation_type.value,
            "activation_score": round(float(self.activation_score), 12),
            "hop_depth": int(self.hop_depth),
            "path": list(self.path),
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "evidence_strength": round(float(self.evidence_strength), 12),
            "evidence": dict(self.evidence),
            "conflict": bool(self.conflict),
        }


@dataclass(frozen=True, slots=True)
class AssociationTraversalResult:
    seed_memory_ids: tuple[str, ...]
    candidates: tuple[AssociationCandidate, ...]
    visited_count: int
    considered_edges: int
    loops_blocked: int
    evidence_rejections: int
    budget_exhausted: bool
    time_budget_exhausted: bool
    elapsed_ms: float
    limits: AssociationLimits
    deterministic_trace: dict[str, Any]
    policy_version: str = ASSOCIATION_POLICY_VERSION


NeighborProvider = Callable[[str, int], Sequence[AssociationNeighbor]]


class SpreadingActivationEngine:
    """Deterministic, bounded graph propagation for shadow associative memory."""

    def __init__(self, limits: AssociationLimits | None = None) -> None:
        self.limits = limits or AssociationLimits()

    @staticmethod
    def _normalize_seeds(seed_memory_ids: Sequence[str]) -> tuple[str, ...]:
        seeds: list[str] = []
        for raw in seed_memory_ids:
            value = str(raw).strip()
            if not value:
                continue
            if len(value) > 160:
                raise ValueError("seed memory id too long")
            if value not in seeds:
                seeds.append(value)
        if not seeds:
            raise ValueError("at least one seed memory is required")
        if len(seeds) > 16:
            raise ValueError("too many seed memories")
        return tuple(seeds)

    def traverse(
        self,
        seed_memory_ids: Sequence[str],
        neighbor_provider: NeighborProvider,
    ) -> AssociationTraversalResult:
        seeds = self._normalize_seeds(seed_memory_ids)
        limits = self.limits
        started = monotonic()
        deadline = started + (limits.time_budget_ms / 1000.0)

        queue: list[tuple[float, int, str, str, tuple[str, ...]]] = []
        for seed in seeds:
            heapq.heappush(queue, (-1.0, 0, seed, seed, (seed,)))

        best_expansion_score: dict[tuple[str, str], float] = {(seed, seed): 1.0 for seed in seeds}
        best_candidates: dict[str, AssociationCandidate] = {}
        visited: set[str] = set(seeds)
        considered_edges = 0
        loops_blocked = 0
        evidence_rejections = 0
        budget_exhausted = False
        time_budget_exhausted = False
        trace_steps: list[dict[str, Any]] = []

        while queue:
            if monotonic() > deadline:
                time_budget_exhausted = True
                break
            negative_score, depth, seed, current, path = heapq.heappop(queue)
            current_score = -negative_score
            if depth >= limits.max_depth:
                continue
            neighbors = sorted(
                tuple(neighbor_provider(current, depth + 1)),
                key=lambda edge: (
                    edge.memory_id,
                    edge.relation_type.value,
                    edge.source_kind,
                    edge.source_ref,
                ),
            )
            if monotonic() > deadline:
                time_budget_exhausted = True
                break
            for edge in neighbors:
                if monotonic() > deadline:
                    time_budget_exhausted = True
                    break
                if considered_edges >= limits.node_budget:
                    budget_exhausted = True
                    break
                considered_edges += 1
                target = edge.memory_id
                if target in path:
                    loops_blocked += 1
                    trace_steps.append(
                        {
                            "seed": seed,
                            "from": current,
                            "to": target,
                            "relation": edge.relation_type.value,
                            "decision": "LOOP_BLOCKED",
                        }
                    )
                    continue
                allowed, reason = evidence_filter(
                    edge.relation_type,
                    evidence_strength=edge.evidence_strength,
                )
                if not allowed:
                    evidence_rejections += 1
                    trace_steps.append(
                        {
                            "seed": seed,
                            "from": current,
                            "to": target,
                            "relation": edge.relation_type.value,
                            "decision": reason,
                        }
                    )
                    continue
                next_depth = depth + 1
                hop_factor = 1.0 if next_depth == 1 else limits.hop_decay
                activation = max(0.0, min(1.0, current_score * float(edge.weight) * hop_factor))
                if activation < limits.min_activation:
                    trace_steps.append(
                        {
                            "seed": seed,
                            "from": current,
                            "to": target,
                            "relation": edge.relation_type.value,
                            "decision": "BELOW_ACTIVATION_THRESHOLD",
                            "activation": round(activation, 12),
                        }
                    )
                    continue

                candidate = AssociationCandidate(
                    seed_memory_id=seed,
                    memory_id=target,
                    relation_type=edge.relation_type,
                    activation_score=activation,
                    hop_depth=next_depth,
                    path=path + (target,),
                    source_kind=edge.source_kind,
                    source_ref=edge.source_ref,
                    evidence_strength=edge.evidence_strength,
                    evidence=edge.evidence,
                    conflict=edge.relation_type is AssociationRelation.CONTRADICTION,
                )
                previous = best_candidates.get(target)
                if previous is None or (
                    candidate.activation_score,
                    -candidate.hop_depth,
                    candidate.relation_type.value,
                    candidate.source_ref,
                ) > (
                    previous.activation_score,
                    -previous.hop_depth,
                    previous.relation_type.value,
                    previous.source_ref,
                ):
                    best_candidates[target] = candidate
                visited.add(target)
                trace_steps.append(
                    {
                        "seed": seed,
                        "from": current,
                        "to": target,
                        "relation": edge.relation_type.value,
                        "decision": "CANDIDATE",
                        "activation": round(activation, 12),
                        "depth": next_depth,
                    }
                )
                expansion_key = (seed, target)
                prior_score = best_expansion_score.get(expansion_key, -1.0)
                if next_depth < limits.max_depth and activation > prior_score:
                    best_expansion_score[expansion_key] = activation
                    heapq.heappush(queue, (-activation, next_depth, seed, target, candidate.path))
            if budget_exhausted or time_budget_exhausted:
                break

        if time_budget_exhausted:
            # Fail closed: wall-clock expiry must never leak a timing-dependent partial candidate set.
            best_candidates.clear()
            visited = set(seeds)
            considered_edges = 0
            loops_blocked = 0
            evidence_rejections = 0
            budget_exhausted = False
            trace_steps = [
                {
                    "decision": "TIME_BUDGET_EXHAUSTED",
                    "policy": "FAIL_CLOSED_NO_PARTIAL_CANDIDATES",
                }
            ]

        candidates = tuple(
            sorted(
                best_candidates.values(),
                key=lambda item: (
                    -item.activation_score,
                    item.hop_depth,
                    item.memory_id,
                    item.relation_type.value,
                    item.source_ref,
                ),
            )[: limits.max_candidates]
        )
        deterministic_trace = {
            "policy_version": ASSOCIATION_POLICY_VERSION,
            "seed_memory_ids": list(seeds),
            "limits": {
                "max_depth": limits.max_depth,
                "node_budget": limits.node_budget,
                "time_budget_ms": limits.time_budget_ms,
                "max_candidates": limits.max_candidates,
                "hop_decay": limits.hop_decay,
                "min_activation": limits.min_activation,
                "semantic_min_similarity": limits.semantic_min_similarity,
            },
            "steps": trace_steps,
            "candidates": [candidate.as_dict() for candidate in candidates],
            "visited_count": len(visited),
            "considered_edges": considered_edges,
            "loops_blocked": loops_blocked,
            "evidence_rejections": evidence_rejections,
            "budget_exhausted": budget_exhausted,
            "time_budget_exhausted": time_budget_exhausted,
        }
        elapsed_ms = (monotonic() - started) * 1000.0
        return AssociationTraversalResult(
            seed_memory_ids=seeds,
            candidates=candidates,
            visited_count=len(visited),
            considered_edges=considered_edges,
            loops_blocked=loops_blocked,
            evidence_rejections=evidence_rejections,
            budget_exhausted=budget_exhausted,
            time_budget_exhausted=time_budget_exhausted,
            elapsed_ms=elapsed_ms,
            limits=limits,
            deterministic_trace=deterministic_trace,
        )
