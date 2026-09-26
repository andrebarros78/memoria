from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any

from .cognitive_observability import metrics
from .consolidation_policy import (
    CONSOLIDATION_POLICY_VERSION,
    ConsolidationCandidateStatus,
    ConsolidationLimits,
    ConsolidationMode,
    ConsolidationTrigger,
    validate_candidate,
)
from .consolidation_replay import (
    ConsolidationReplay,
    ConsolidationSourceSnapshot,
    build_replay,
    replay_matches,
)

CONSOLIDATION_ENGINE_VERSION = "OCC-1.0.0"
_CONSOLIDATION_STAGES = (
    "SELECT",
    "REPLAY",
    "COMPARE",
    "CLUSTER",
    "ASSOCIATE",
    "DETECT_PATTERN",
    "GENERATE_CANDIDATE",
    "VALIDATE",
    "CONSOLIDATE",
    "RECORD_PROVENANCE",
)


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


class ForcedConsolidationInterruption(RuntimeError):
    """Proof-only interruption injected after a durable stage checkpoint."""


@dataclass(frozen=True, slots=True)
class ConsolidationCandidate:
    candidate_id: str
    candidate_kind: str
    source_memory_ids: tuple[str, ...]
    confidence: float
    conflict: bool
    status: ConsolidationCandidateStatus
    proof_refs: tuple[str, ...]
    proof: dict[str, Any]
    candidate_digest: str
    rejection_reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_kind": self.candidate_kind,
            "source_memory_ids": list(self.source_memory_ids),
            "sample_count": len(self.source_memory_ids),
            "confidence": self.confidence,
            "conflict": self.conflict,
            "status": self.status.value,
            "proof_refs": list(self.proof_refs),
            "proof": self.proof,
            "candidate_digest": self.candidate_digest,
            "rejection_reasons": list(self.rejection_reasons),
        }


@dataclass(frozen=True, slots=True)
class ConsolidationRunResult:
    run_id: str
    mode: str
    status: str
    source_count: int
    candidate_count: int
    validated_candidate_count: int
    replay_digest: str
    elapsed_ms: float
    recovered_from_interrupt: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "source_count": self.source_count,
            "candidate_count": self.candidate_count,
            "validated_candidate_count": self.validated_candidate_count,
            "replay_digest": self.replay_digest,
            "elapsed_ms": self.elapsed_ms,
            "recovered_from_interrupt": self.recovered_from_interrupt,
        }


class PostgresConsolidationStore:
    """F04 persistence adapter. It reads canonical evidence and writes only SHADOW state."""

    def __init__(self, memory_store: Any) -> None:
        self.memory_store = memory_store

    @property
    def tenant_id(self) -> str:
        return str(self.memory_store.tenant_id)

    def _scope_values(self, *, mission_id: str | None = None, session_id: str | None = None) -> tuple[str, str, str]:
        access = self.memory_store.access
        return str(access.project_id or ""), str(mission_id or ""), str(session_id or "")

    @staticmethod
    def _snapshot(row: Any) -> ConsolidationSourceSnapshot:
        return ConsolidationSourceSnapshot(
            memory_id=str(row["item_id"]),
            namespace=str(row["namespace"]),
            category=str(row["category"]),
            content_sha256=str(row["content_sha256"]),
            confidence=_bounded(row.get("confidence") or 0.0),
            salience=_bounded(row.get("salience") or 0.0),
            activation=_bounded(row.get("activation") or 0.0),
            outcome_signal=_bounded(row.get("outcome_signal") or 0.0),
            association_signal=_bounded(row.get("association_signal") or 0.0),
            conflict=bool(row.get("conflict") or False),
        )

    def select_sources(
        self,
        *,
        limit: int,
        mission_id: str | None = None,
        session_id: str | None = None,
    ) -> tuple[ConsolidationSourceSnapshot, ...]:
        project_id, mission_scope, session_scope = self._scope_values(
            mission_id=mission_id, session_id=session_id
        )
        safe_limit = max(2, min(int(limit), 512))
        with self.memory_store.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_consolidation_source_snapshot(NULL,%s,%s,%s,%s)",
                (safe_limit, project_id, mission_scope, session_scope),
            ).fetchall()
        return tuple(self._snapshot(row) for row in rows)

    def fetch_sources(
        self,
        memory_ids: Sequence[str],
        *,
        mission_id: str | None = None,
        session_id: str | None = None,
    ) -> tuple[ConsolidationSourceSnapshot, ...]:
        ids = tuple(dict.fromkeys(str(item).strip() for item in memory_ids if str(item).strip()))
        if not ids:
            return ()
        if len(ids) > 512:
            raise ValueError("source replay set exceeds bound")
        project_id, mission_scope, session_scope = self._scope_values(
            mission_id=mission_id, session_id=session_id
        )
        with self.memory_store.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_consolidation_source_snapshot(%s,%s,%s,%s,%s)",
                (list(ids), len(ids), project_id, mission_scope, session_scope),
            ).fetchall()
        found = {str(row["item_id"]): self._snapshot(row) for row in rows}
        return tuple(found[item_id] for item_id in ids if item_id in found)

    def start_run(
        self,
        *,
        run_id: str,
        scope_key: str,
        mode: ConsolidationMode,
        trigger: ConsolidationTrigger,
        lease_key: str,
        fencing_token: int,
        mission_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        project_id, mission_scope, session_scope = self._scope_values(
            mission_id=mission_id, session_id=session_id
        )
        with self.memory_store.connection() as conn:
            row = conn.execute(
                "SELECT memory_start_consolidation_shadow(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) AS run_id",
                (
                    run_id, scope_key, mode.value, trigger.value, lease_key, int(fencing_token),
                    CONSOLIDATION_POLICY_VERSION, project_id, mission_scope, session_scope,
                ),
            ).fetchone()
        return str(row["run_id"])

    def resume_run(self, *, run_id: str, lease_key: str, fencing_token: int) -> str:
        with self.memory_store.connection() as conn:
            row = conn.execute(
                "SELECT memory_resume_consolidation_shadow(%s,%s,%s) AS run_id",
                (run_id, lease_key, int(fencing_token)),
            ).fetchone()
        return str(row["run_id"])

    def checkpoint(self, *, run_id: str, sequence_no: int, stage: str, state: dict[str, Any]) -> str:
        if stage not in _CONSOLIDATION_STAGES:
            raise ValueError("invalid consolidation stage")
        checkpoint_id = f"concp-{uuid.uuid4().hex}"
        state_sha = _sha(state)
        with self.memory_store.connection() as conn:
            row = conn.execute(
                "SELECT memory_checkpoint_consolidation_shadow(%s,%s,%s,%s,%s::jsonb,%s) AS checkpoint_id",
                (run_id, checkpoint_id, int(sequence_no), stage, _canon(state), state_sha),
            ).fetchone()
        return str(row["checkpoint_id"])

    def record_candidate(self, *, run_id: str, candidate: ConsolidationCandidate) -> str:
        with self.memory_store.connection() as conn:
            row = conn.execute(
                "SELECT memory_record_consolidation_candidate_shadow(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb) AS candidate_id",
                (
                    run_id,
                    candidate.candidate_id,
                    candidate.candidate_kind,
                    list(candidate.source_memory_ids),
                    candidate.status.value,
                    candidate.confidence,
                    candidate.conflict,
                    _canon(candidate.proof),
                    candidate.candidate_digest,
                    _canon({"proof_refs": list(candidate.proof_refs), "rejection_reasons": list(candidate.rejection_reasons)}),
                ),
            ).fetchone()
        return str(row["candidate_id"])

    def finish_run(self, *, run_id: str, source_count: int, replay_digest: str) -> dict[str, Any]:
        with self.memory_store.connection() as conn:
            row = conn.execute(
                "SELECT * FROM memory_finish_consolidation_shadow(%s,%s,%s)",
                (run_id, int(source_count), replay_digest),
            ).fetchone()
        return dict(row)

    def load_run(self, run_id: str) -> dict[str, Any] | None:
        with self.memory_store.connection() as conn:
            row = conn.execute("SELECT * FROM cognitive_consolidation_runs WHERE run_id=%s", (run_id,)).fetchone()
        return dict(row) if row else None

    def checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        with self.memory_store.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM cognitive_consolidation_checkpoints WHERE run_id=%s ORDER BY sequence_no,created_at,checkpoint_id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def candidates(self, run_id: str) -> list[dict[str, Any]]:
        with self.memory_store.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM cognitive_consolidation_candidates WHERE run_id=%s ORDER BY candidate_id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]


class OfflineCognitiveConsolidationEngine:
    """Deterministic background-only F04 engine. It never mutates canonical memory truth."""

    def __init__(self, store: PostgresConsolidationStore, *, limits: ConsolidationLimits | None = None) -> None:
        self.store = store
        self.limits = limits or ConsolidationLimits()

    def _generate_candidates(
        self,
        run_id: str,
        sources: Sequence[ConsolidationSourceSnapshot],
        replay: ConsolidationReplay,
    ) -> tuple[ConsolidationCandidate, ...]:
        groups: dict[tuple[str, str], list[ConsolidationSourceSnapshot]] = defaultdict(list)
        for source in sources:
            groups[(source.namespace, source.category)].append(source)
        candidates: list[ConsolidationCandidate] = []
        for (namespace, category), group in sorted(groups.items()):
            ordered = tuple(sorted(group, key=lambda source: source.memory_id))
            if len(ordered) < self.limits.min_sample:
                continue
            avg_conf = sum(source.confidence for source in ordered) / len(ordered)
            avg_salience = sum(source.salience for source in ordered) / len(ordered)
            avg_activation = sum(source.activation for source in ordered) / len(ordered)
            avg_outcome = sum(source.outcome_signal for source in ordered) / len(ordered)
            avg_assoc = sum(source.association_signal for source in ordered) / len(ordered)
            confidence = _bounded(
                avg_conf * 0.50 + avg_salience * 0.15 + avg_activation * 0.15 + avg_outcome * 0.10 + avg_assoc * 0.10
            )
            conflict = any(source.conflict for source in ordered)
            if conflict:
                kind = "CONFLICT_CLUSTER"
            elif avg_outcome >= 0.50:
                kind = "OUTCOME_CLUSTER"
            elif avg_salience >= 0.70:
                kind = "HIGH_SALIENCE_CLUSTER"
            elif avg_assoc >= 0.50:
                kind = "ASSOCIATION_CLUSTER"
            else:
                kind = "REPEATED_PATTERN"
            proof_refs = tuple(source.proof_ref() for source in ordered)
            status, reasons = validate_candidate(
                sample_count=len(ordered),
                confidence=confidence,
                conflict=conflict,
                proof_count=len(proof_refs),
                limits=self.limits,
            )
            source_ids = tuple(source.memory_id for source in ordered)
            proof = {
                "policy_version": CONSOLIDATION_POLICY_VERSION,
                "replay_digest": replay.replay_digest,
                "source_digest": replay.source_digest,
                "namespace": namespace,
                "category": category,
                "sample_count": len(ordered),
                "signals": {
                    "confidence": round(avg_conf, 8),
                    "salience": round(avg_salience, 8),
                    "activation": round(avg_activation, 8),
                    "outcome": round(avg_outcome, 8),
                    "association": round(avg_assoc, 8),
                },
                "truth_mutated": False,
            }
            digest = _sha({"run_id": run_id, "kind": kind, "sources": source_ids, "proof": proof})
            candidates.append(
                ConsolidationCandidate(
                    candidate_id=f"concand-{digest[:32]}",
                    candidate_kind=kind,
                    source_memory_ids=source_ids,
                    confidence=confidence,
                    conflict=conflict,
                    status=status,
                    proof_refs=proof_refs,
                    proof=proof,
                    candidate_digest=digest,
                    rejection_reasons=reasons,
                )
            )
        return tuple(sorted(candidates, key=lambda candidate: (-candidate.confidence, candidate.candidate_id))[: self.limits.max_candidates])

    def _checkpoint(self, run_id: str, sequence_no: int, stage: str, state: dict[str, Any], interrupt_after_stage: str | None) -> None:
        self.store.checkpoint(run_id=run_id, sequence_no=sequence_no, stage=stage, state=state)
        if interrupt_after_stage == stage:
            raise ForcedConsolidationInterruption(f"forced interruption after durable {stage} checkpoint")

    def execute(
        self,
        *,
        scope_key: str,
        mode: ConsolidationMode,
        trigger: ConsolidationTrigger,
        lease_key: str,
        fencing_token: int,
        run_id: str | None = None,
        interrupt_after_stage: str | None = None,
        mission_id: str | None = None,
        session_id: str | None = None,
    ) -> ConsolidationRunResult:
        started = monotonic()
        identifier = run_id or f"conrun-{uuid.uuid4().hex}"
        self.store.start_run(
            run_id=identifier,
            scope_key=scope_key,
            mode=mode,
            trigger=trigger,
            lease_key=lease_key,
            fencing_token=fencing_token,
            mission_id=mission_id,
            session_id=session_id,
        )
        sources = self.store.select_sources(
            limit=self.limits.max_sources, mission_id=mission_id, session_id=session_id
        )
        self._checkpoint(
            identifier,
            1,
            "SELECT",
            {"source_ids": [source.memory_id for source in sources], "source_count": len(sources), "content_in_checkpoint": False},
            interrupt_after_stage,
        )
        return self._continue(identifier, mode, sources, started, sequence_start=2, interrupt_after_stage=interrupt_after_stage, recovered=False)

    def recover(
        self,
        *,
        run_id: str,
        lease_key: str,
        fencing_token: int,
    ) -> ConsolidationRunResult:
        started = monotonic()
        run = self.store.load_run(run_id)
        if not run:
            raise KeyError(run_id)
        if str(run["status"]) == "COMPLETED":
            replay_check = self.replay_run(run_id)
            return ConsolidationRunResult(
                run_id=run_id,
                mode=str(run["mode"]),
                status="COMPLETED",
                source_count=int(run["source_count"] or 0),
                candidate_count=int(run["candidate_count"] or 0),
                validated_candidate_count=int(run["validated_candidate_count"] or 0),
                replay_digest=str(replay_check["replay_digest"]),
                elapsed_ms=0.0,
                recovered_from_interrupt=bool(run["recovered_from_interrupt"]),
            )
        self.store.resume_run(run_id=run_id, lease_key=lease_key, fencing_token=fencing_token)
        checkpoints = self.store.checkpoints(run_id)
        select_checkpoints = [row for row in checkpoints if row["stage"] == "SELECT"]
        if not select_checkpoints:
            raise RuntimeError("recovery requires durable SELECT checkpoint")
        source_ids = list(select_checkpoints[0]["state_jsonb"].get("source_ids") or [])
        sources = self.store.fetch_sources(
            source_ids, mission_id=str(run.get("mission_id") or "") or None,
            session_id=str(run.get("session_id") or "") or None,
        )
        if tuple(source_ids) != tuple(source.memory_id for source in sources):
            raise RuntimeError("recovery source set changed or became invisible")
        sequence_start = max(int(row["sequence_no"]) for row in checkpoints) + 1
        mode = ConsolidationMode(str(run["mode"]))
        return self._continue(run_id, mode, sources, started, sequence_start=sequence_start, interrupt_after_stage=None, recovered=True)

    def _continue(
        self,
        run_id: str,
        mode: ConsolidationMode,
        sources: Sequence[ConsolidationSourceSnapshot],
        started: float,
        *,
        sequence_start: int,
        interrupt_after_stage: str | None,
        recovered: bool,
    ) -> ConsolidationRunResult:
        replay = build_replay(sources)
        seq = sequence_start
        self._checkpoint(run_id, seq, "REPLAY", dict(replay.trace), interrupt_after_stage)
        seq += 1
        self._checkpoint(run_id, seq, "COMPARE", {"source_digest": replay.source_digest, "conflicts": sum(1 for source in sources if source.conflict)}, interrupt_after_stage)
        seq += 1
        cluster_count = len(replay.cluster_keys)
        self._checkpoint(run_id, seq, "CLUSTER", {"cluster_keys": list(replay.cluster_keys), "cluster_count": cluster_count}, interrupt_after_stage)
        seq += 1
        association_sources = sum(1 for source in sources if source.association_signal > 0.0)
        self._checkpoint(run_id, seq, "ASSOCIATE", {"association_evidence_sources": association_sources}, interrupt_after_stage)
        seq += 1
        candidates = self._generate_candidates(run_id, sources, replay)
        self._checkpoint(run_id, seq, "DETECT_PATTERN", {"candidate_count": len(candidates)}, interrupt_after_stage)
        seq += 1
        self._checkpoint(run_id, seq, "GENERATE_CANDIDATE", {"candidate_ids": [candidate.candidate_id for candidate in candidates]}, interrupt_after_stage)
        seq += 1
        for candidate in candidates:
            self.store.record_candidate(run_id=run_id, candidate=candidate)
        validated = sum(1 for candidate in candidates if candidate.status is ConsolidationCandidateStatus.VALIDATED_SHADOW)
        rejected = len(candidates) - validated
        self._checkpoint(run_id, seq, "VALIDATE", {"validated": validated, "rejected": rejected}, interrupt_after_stage)
        seq += 1
        self._checkpoint(run_id, seq, "CONSOLIDATE", {"consolidated_shadow": validated, "canonical_promotions": 0}, interrupt_after_stage)
        seq += 1
        self._checkpoint(
            run_id,
            seq,
            "RECORD_PROVENANCE",
            {"replay_digest": replay.replay_digest, "source_digest": replay.source_digest, "policy_version": CONSOLIDATION_POLICY_VERSION},
            interrupt_after_stage,
        )
        finished = self.store.finish_run(run_id=run_id, source_count=len(sources), replay_digest=replay.replay_digest)
        elapsed_ms = max(0.0, (monotonic() - started) * 1000.0)
        if elapsed_ms > self.limits.max_run_ms:
            raise RuntimeError("consolidation run exceeded bounded time budget")
        metrics.increment("consolidation_runs_total")
        if len(candidates):
            metrics.increment("consolidation_candidates_total", len(candidates))
        return ConsolidationRunResult(
            run_id=run_id,
            mode=mode.value,
            status=str(finished["status"]),
            source_count=len(sources),
            candidate_count=len(candidates),
            validated_candidate_count=validated,
            replay_digest=replay.replay_digest,
            elapsed_ms=elapsed_ms,
            recovered_from_interrupt=bool(finished["recovered_from_interrupt"]),
        )

    def replay_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.load_run(run_id)
        if not run:
            raise KeyError(run_id)
        checkpoints = self.store.checkpoints(run_id)
        select_checkpoints = [row for row in checkpoints if row["stage"] == "SELECT"]
        replay_checkpoints = [row for row in checkpoints if row["stage"] == "REPLAY"]
        if not select_checkpoints or not replay_checkpoints:
            raise RuntimeError("run has insufficient replay evidence")
        source_ids = list(select_checkpoints[0]["state_jsonb"].get("source_ids") or [])
        sources = self.store.fetch_sources(
            source_ids, mission_id=str(run.get("mission_id") or "") or None,
            session_id=str(run.get("session_id") or "") or None,
        )
        expected = replay_checkpoints[-1]["state_jsonb"]
        ok = replay_matches(
            sources,
            expected_source_digest=str(expected.get("source_digest") or ""),
            expected_replay_digest=str(expected.get("replay_digest") or ""),
        )
        replay = build_replay(sources)
        persisted = self.store.candidates(run_id)
        return {
            "status": "PASS" if ok else "FAIL",
            "run_id": run_id,
            "source_count": len(sources),
            "candidate_count": len(persisted),
            "source_digest": replay.source_digest,
            "replay_digest": replay.replay_digest,
            "deterministic": ok,
        }


def offline_consolidation_spec() -> dict[str, Any]:
    return {
        "version": CONSOLIDATION_ENGINE_VERSION,
        "policy_version": CONSOLIDATION_POLICY_VERSION,
        "capability_class": "OPTIONAL_ASYNC",
        "mode": "SHADOW",
        "pipeline": list(_CONSOLIDATION_STAGES),
        "canonical_truth_mutation": False,
        "capture_retrieval_dependency": False,
        "candidate_only": True,
        "replayable": True,
        "checkpointed": True,
        "recoverable_after_interruption": True,
    }
