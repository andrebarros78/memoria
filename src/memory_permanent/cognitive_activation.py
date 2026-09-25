from __future__ import annotations

import json
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .activation_trace import ActivationTrace
from .cognitive_contracts import CognitiveScope
from .cognitive_observability import dispatcher, metrics
from .priming_policy import PrimingDecision, evaluate_priming
from .provenance_policy import is_system_assigned_trust
from .salience_engine import SalienceEngine, SalienceResult
from .salience_policy import SALIENCE_DIMENSIONS
from .spreading_activation import SpreadingActivationEngine

ACTIVATION_POLICY_VERSION = "ACT-1.0.0"
ACTIVATION_HALF_LIFE_HOURS = 72.0


def _unit(name: str, value: float) -> float:
    result = float(value)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return result


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ActivationResult:
    memory_id: str
    activation_level: float
    base_strength: float
    access_count: int
    recent_access_weight: float
    priming_weight: float
    association_activation: float
    goal_activation: float
    context_activation: float
    interference_penalty: float
    habituation_penalty: float
    trace: ActivationTrace


class CognitiveActivationEngine:
    """Deterministic bounded activation engine; it never mutates memory truth."""

    def __init__(self, *, half_life_hours: float = ACTIVATION_HALF_LIFE_HOURS) -> None:
        half_life = float(half_life_hours)
        if not 1.0 <= half_life <= 24.0 * 365.0:
            raise ValueError("half_life_hours out of bounds")
        self.half_life_hours = half_life

    def compute(
        self,
        *,
        memory_id: str,
        base_strength: float,
        last_activated_at: datetime | None,
        access_count: int,
        priming_weight: float = 0.0,
        association_activation: float = 0.0,
        goal_relevance: float = 0.0,
        context_match: float = 0.0,
        interference_penalty: float = 0.0,
        habituation_penalty: float = 0.0,
        now: datetime | None = None,
        trace_id: str | None = None,
    ) -> ActivationResult:
        if not str(memory_id).strip():
            raise ValueError("memory_id is required")
        current = (now or datetime.now(UTC)).astimezone(UTC)
        last = last_activated_at.astimezone(UTC) if last_activated_at is not None else None
        if last is not None and last > current:
            raise ValueError("last_activated_at cannot be in the future")
        accesses = int(access_count)
        if accesses < 0 or accesses > 10**12:
            raise ValueError("access_count out of bounds")

        base = _unit("base_strength", base_strength)
        priming = _unit("priming_weight", priming_weight)
        association = _unit("association_activation", association_activation)
        goal = _unit("goal_relevance", goal_relevance)
        context = _unit("context_match", context_match)
        interference = min(_unit("interference_penalty", interference_penalty), 0.25)
        habituation = min(_unit("habituation_penalty", habituation_penalty), 0.10)

        age_hours = self.half_life_hours if last is None else max((current - last).total_seconds() / 3600.0, 0.0)
        decay_ratio = 1.0 - math.exp(-math.log(2.0) * age_hours / self.half_life_hours)
        recency_ratio = 1.0 - decay_ratio
        recency_boost = recency_ratio * 0.15
        frequency_boost = min(math.log1p(accesses) / math.log1p(100.0), 1.0) * 0.10
        priming_boost = min(priming, 0.20)
        context_component = context * 0.10
        goal_component = goal * 0.10
        association_component = association * 0.05
        base_component = base * 0.40
        temporal_decay = decay_ratio * 0.15

        raw = (
            base_component
            + recency_boost
            + frequency_boost
            + priming_boost
            + context_component
            + goal_component
            + association_component
            - temporal_decay
            - interference
            - habituation
        )
        level = min(max(raw, 0.0), 1.0)
        components = {
            "base_strength": base_component,
            "recency_boost": recency_boost,
            "frequency_boost": frequency_boost,
            "priming_boost": priming_boost,
            "context_match": context_component,
            "goal_relevance": goal_component,
            "associative_activation": association_component,
            "temporal_decay": temporal_decay,
            "interference": interference,
            "habituation": habituation,
        }
        trace = ActivationTrace(
            memory_id=str(memory_id),
            activation_level=level,
            components=components,
            policy_version=ACTIVATION_POLICY_VERSION,
            trace_id=trace_id,
            computed_at=current,
        )
        return ActivationResult(
            memory_id=str(memory_id),
            activation_level=level,
            base_strength=base,
            access_count=accesses,
            recent_access_weight=recency_boost,
            priming_weight=priming_boost,
            association_activation=association,
            goal_activation=goal,
            context_activation=context,
            interference_penalty=interference,
            habituation_penalty=habituation,
            trace=trace,
        )


class PostgresActivationStore:
    """Concrete ActivationStorePort over the public PostgresMemoryStore connection boundary."""

    def __init__(self, memory_store: Any) -> None:
        self.memory_store = memory_store

    def load_activation_state(self, memory_id: str) -> dict[str, Any] | None:
        with self.memory_store.connection() as conn:
            row = conn.execute(
                """
                SELECT memory_id,base_strength,activation_level,activation_updated_at,access_count,
                       recent_access_weight,priming_weight,association_activation,goal_activation,
                       context_activation,interference_penalty,habituation_penalty,decay_policy_version,trace_jsonb
                FROM memory_activation_state WHERE memory_id=%s
                """,
                (memory_id,),
            ).fetchone()
        return dict(row) if row else None

    def load_priming_weight(self, memory_id: str) -> float:
        with self.memory_store.connection() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(sum(weight),0.0) AS weight
                FROM memory_priming_edges
                WHERE target_memory_id=%s AND (valid_until IS NULL OR valid_until>now())
                """,
                (memory_id,),
            ).fetchone()
        return min(max(float(row["weight"] if row else 0.0), 0.0), 0.20)

    def record_activation_shadow(self, result: ActivationResult, *, trace_id: str | None) -> str:
        event_id = f"actevt-{uuid.uuid4().hex}"
        with self.memory_store.connection() as conn:
            conn.execute(
                """
                SELECT memory_record_activation_shadow(
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s
                )
                """,
                (
                    event_id,
                    result.memory_id,
                    result.base_strength,
                    result.activation_level,
                    result.access_count,
                    result.recent_access_weight,
                    result.priming_weight,
                    result.association_activation,
                    result.goal_activation,
                    result.context_activation,
                    result.interference_penalty,
                    result.habituation_penalty,
                    ACTIVATION_POLICY_VERSION,
                    json.dumps(result.trace.as_dict(), sort_keys=True),
                    trace_id,
                ),
            )
        return event_id

    def record_priming_shadow(
        self,
        *,
        target_memory_id: str,
        decision: PrimingDecision,
        source_memory_id: str | None,
        evidence_refs: tuple[str, ...],
        trace_id: str | None,
        ttl_seconds: int = 3600,
    ) -> str:
        edge_id = f"prime-{uuid.uuid4().hex}"
        with self.memory_store.connection() as conn:
            conn.execute(
                "SELECT memory_record_priming_shadow(%s,%s,%s,%s,%s,%s::jsonb,%s,%s)",
                (
                    edge_id,
                    target_memory_id,
                    source_memory_id,
                    decision.boost,
                    float(decision.trace["source_trust"]),
                    json.dumps(list(dict.fromkeys(evidence_refs))),
                    trace_id,
                    min(max(int(ttl_seconds), 1), 86400),
                ),
            )
        return edge_id

    def record_salience_shadow(
        self,
        *,
        memory_id: str,
        result: SalienceResult,
        evidence_refs: tuple[str, ...],
        trace_id: str | None,
    ) -> str:
        salience_id = f"sal-{uuid.uuid4().hex}"
        with self.memory_store.connection() as conn:
            conn.execute(
                "SELECT memory_record_salience_shadow(%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s)",
                (
                    salience_id,
                    memory_id,
                    result.score,
                    json.dumps(dict(result.dimensions), sort_keys=True),
                    result.policy_version,
                    json.dumps(result.explanation.as_dict(), sort_keys=True),
                    json.dumps(list(dict.fromkeys(evidence_refs))),
                    trace_id,
                ),
            )
        return salience_id


class CognitiveShadowObserver:
    """Shadow-only integration. It records cognition without changing retrieval decisions."""

    def __init__(
        self,
        store: Any,
        *,
        activation_enabled: bool = True,
        priming_enabled: bool = True,
        salience_enabled: bool = True,
        association_enabled: bool = False,
        activation_engine: CognitiveActivationEngine | None = None,
        salience_engine: SalienceEngine | None = None,
        association_store: Any | None = None,
        spreading_engine: SpreadingActivationEngine | None = None,
    ) -> None:
        self.store = store
        self.activation_enabled = bool(activation_enabled)
        self.priming_enabled = bool(priming_enabled)
        self.salience_enabled = bool(salience_enabled)
        self.association_enabled = bool(association_enabled)
        self.activation_engine = activation_engine or CognitiveActivationEngine()
        self.salience_engine = salience_engine or SalienceEngine()
        self.association_store = association_store
        self.spreading_engine = spreading_engine or SpreadingActivationEngine()
        if self.association_enabled and self.association_store is None:
            raise ValueError("association_store is required when association is enabled")

    def observe_capture(
        self,
        *,
        memory_id: str,
        base_strength: float,
        salience_signals: Mapping[str, float] | None = None,
        source_trust: float = 0.5,
        evidence_refs: tuple[str, ...] = (),
    ) -> None:
        if self.activation_enabled:
            result = self.activation_engine.compute(
                memory_id=memory_id,
                base_strength=base_strength,
                last_activated_at=datetime.now(UTC),
                access_count=0,
            )
            self.store.record_activation_shadow(result, trace_id=None)
            metrics.increment("memory_activation_total")
        if self.salience_enabled and salience_signals:
            dimensions = {
                name: float(salience_signals[name])
                for name in SALIENCE_DIMENSIONS
                if name in salience_signals
            }
            salience = self.salience_engine.compute(
                dimensions,
                source_trust=source_trust,
                independent_evidence_count=len(set(evidence_refs)),
            )
            self.store.record_salience_shadow(
                memory_id=memory_id,
                result=salience,
                evidence_refs=evidence_refs,
                trace_id=None,
            )
            metrics.increment("salience_computations_total")

    def submit_capture(
        self,
        *,
        memory_id: str,
        base_strength: float,
        salience_signals: Mapping[str, float] | None = None,
        source_trust: float = 0.5,
        evidence_refs: tuple[str, ...] = (),
    ) -> bool:
        signals = dict(salience_signals or {})
        refs = tuple(evidence_refs)
        return dispatcher.submit(
            self.observe_capture,
            memory_id=memory_id,
            base_strength=base_strength,
            salience_signals=signals,
            source_trust=source_trust,
            evidence_refs=refs,
        )

    def submit_retrieval(
        self,
        *,
        selected: tuple[dict[str, Any], ...],
        trace_id: str,
        namespaces: tuple[str, ...] = (),
        mission_id: str | None = None,
        session_id: str | None = None,
    ) -> bool:
        snapshot = tuple(dict(item) for item in selected)
        return dispatcher.submit(
            self.observe_retrieval,
            selected=snapshot,
            trace_id=trace_id,
            namespaces=tuple(namespaces),
            mission_id=mission_id,
            session_id=session_id,
        )

    def observe_retrieval(
        self,
        *,
        selected: tuple[dict[str, Any], ...],
        trace_id: str,
        namespaces: tuple[str, ...] = (),
        mission_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        for item in selected:
            memory_id = str(item.get("item_id") or "").strip()
            if not memory_id:
                continue
            state = self.store.load_activation_state(memory_id) if self.activation_enabled else None
            priming_weight = self.store.load_priming_weight(memory_id) if self.activation_enabled else 0.0
            if self.activation_enabled:
                last = _parse_time((state or {}).get("activation_updated_at") or item.get("last_used_at") or item.get("created_at"))
                access_count = int((state or {}).get("access_count") or item.get("retrieval_count") or 0) + 1
                result = self.activation_engine.compute(
                    memory_id=memory_id,
                    base_strength=float((state or {}).get("base_strength") or item.get("confidence") or 0.5),
                    last_activated_at=last,
                    access_count=access_count,
                    priming_weight=priming_weight,
                    association_activation=float((state or {}).get("association_activation") or 0.0),
                    goal_relevance=float((state or {}).get("goal_activation") or 0.0),
                    context_match=float((state or {}).get("context_activation") or 0.0),
                    interference_penalty=float((state or {}).get("interference_penalty") or 0.0),
                    habituation_penalty=float((state or {}).get("habituation_penalty") or 0.0),
                    trace_id=trace_id,
                )
                self.store.record_activation_shadow(result, trace_id=trace_id)
                metrics.increment("memory_activation_total")

            if self.salience_enabled:
                provenance = item.get("provenance") or {}
                content = item.get("content_json") or {}
                if not isinstance(provenance, Mapping):
                    provenance = {}
                if not isinstance(content, Mapping):
                    content = {}
                raw_dimensions = provenance.get("salience_signals") or content.get("salience_signals") or {}
                if isinstance(raw_dimensions, Mapping) and raw_dimensions:
                    dimensions = {name: float(raw_dimensions[name]) for name in SALIENCE_DIMENSIONS if name in raw_dimensions}
                    evidence_refs = tuple(str(x) for x in provenance.get("evidence_refs", ()) if str(x).strip())
                    salience = self.salience_engine.compute(
                        dimensions,
                        source_trust=1.0 if is_system_assigned_trust(dict(provenance)) else 0.5,
                        independent_evidence_count=len(set(evidence_refs)),
                    )
                    self.store.record_salience_shadow(
                        memory_id=memory_id,
                        result=salience,
                        evidence_refs=evidence_refs,
                        trace_id=trace_id,
                    )
                    metrics.increment("salience_computations_total")

        if self.association_enabled and self.association_store is not None and selected:
            seed_ids = tuple(str(item.get("item_id") or "").strip() for item in selected)
            seed_ids = tuple(item_id for item_id in seed_ids if item_id)
            association_namespaces = tuple(
                str(value).strip().upper() for value in namespaces if str(value).strip()
            ) or tuple(
                sorted({str(item.get("namespace") or "").strip().upper() for item in selected if str(item.get("namespace") or "").strip()})
            )
            if seed_ids and association_namespaces:
                limits = self.spreading_engine.limits
                result = self.spreading_engine.traverse(
                    seed_ids,
                    lambda memory_id, _depth: self.association_store.neighbors(
                        memory_id,
                        namespaces=association_namespaces,
                        mission_id=mission_id,
                        session_id=session_id,
                        semantic_min_similarity=limits.semantic_min_similarity,
                        limit=min(32, limits.node_budget),
                    ),
                )
                self.association_store.record_traversal_shadow(
                    result,
                    retrieval_trace_id=trace_id,
                    mission_id=mission_id,
                    session_id=session_id,
                )
                metrics.increment("association_traversals_total")

    def prime(
        self,
        *,
        target_memory_id: str,
        source_scope: CognitiveScope,
        target_scope: CognitiveScope,
        requested_boost: float,
        source_trust: float,
        budget_remaining: float,
        evidence_refs: tuple[str, ...] = (),
        source_memory_id: str | None = None,
        trace_id: str | None = None,
        ttl_seconds: int = 3600,
    ) -> PrimingDecision:
        decision = evaluate_priming(
            source_scope=source_scope,
            target_scope=target_scope,
            requested_boost=requested_boost,
            source_trust=source_trust,
            budget_remaining=budget_remaining,
            evidence_refs=evidence_refs,
        )
        if self.priming_enabled and decision.allowed and decision.boost > 0.0:
            self.store.record_priming_shadow(
                target_memory_id=target_memory_id,
                decision=decision,
                source_memory_id=source_memory_id,
                evidence_refs=evidence_refs,
                trace_id=trace_id,
                ttl_seconds=ttl_seconds,
            )
            metrics.increment("priming_events_total")
        return decision

    @staticmethod
    def record_failure() -> None:
        metrics.increment("cognitive_shadow_failures_total")
