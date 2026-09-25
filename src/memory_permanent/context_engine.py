from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .canonical_mutation import CanonicalMutationRequired, CanonicalMutationService
from .embedding_provider import EmbeddingProviderAdapter

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ContextResult:
    query: str
    selected: tuple[dict[str, Any], ...]
    conflicts: tuple[dict[str, Any], ...]
    trace_id: str
    state: dict[str, Any] | None = None
    retrieval_modes: tuple[str, ...] = ()


class ContextEngine:
    """Compositor determinístico: busca lexical + semântica + estado/checkpoint."""

    def __init__(
        self,
        store: Any,
        embedding_provider: EmbeddingProviderAdapter | None = None,
        *,
        semantic_min_similarity: float = 0.40,
        cognitive_observer: Any | None = None,
    ) -> None:
        threshold = float(semantic_min_similarity)
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("semantic_min_similarity must be between 0 and 1")
        self.store = store
        self.embedding_provider = embedding_provider
        self.semantic_min_similarity = threshold
        self.cognitive_observer = cognitive_observer
        self.mutations = CanonicalMutationService(store, actor_id="context-engine")

    def remember(self, **kwargs: Any) -> str:
        raise CanonicalMutationRequired("ContextEngine is read/composition only; use CanonicalMutationService for writes")

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if len(a) != len(b) or not a:
            return -1.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0.0 or nb == 0.0:
            return -1.0
        return dot / (na * nb)

    @staticmethod
    def _score(item: dict[str, Any]) -> float:
        lifecycle = str(item.get("lifecycle_state") or "HOT")
        lifecycle_weight = {
            "HOT": 3.0,
            "WARM": 2.0,
            "COLD": 0.5,
            "DELETE_ELIGIBLE": -1.0,
            "QUARANTINED": -100.0,
            "PURGED": -1000.0,
        }.get(lifecycle, 0.0)
        operator = str(item.get("operator_class") or "ATIVA")
        operator_weight = {
            "PERMANENTE": 4.0,
            "PROTEGIDA": 3.5,
            "ATIVA": 2.0,
            "ARQUIVADA": 0.5,
            "DESCARTÁVEL": -1.0,
        }.get(operator, 0.0)
        return (
            (100.0 if bool(item.get("exact_substring_match")) else 0.0)
            + float(item.get("semantic_similarity") or 0.0) * 10.0
            + float(item.get("text_rank") or 0.0) * 10.0
            + float(item.get("confidence") or 0.0) * 5.0
            + lifecycle_weight
            + operator_weight
        )

    def _semantic_candidates(
        self,
        query: str,
        namespaces: list[str],
        limit: int,
        *,
        mission_id: str | None = None,
        session_id: str | None = None,
        valid_at: datetime | None = None,
        known_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if self.embedding_provider is None:
            return []
        query_vector = self.embedding_provider.embed_query(query)
        if hasattr(self.store, "semantic_search_pgvector"):
            try:
                try:
                    rows = self.store.semantic_search_pgvector(
                        namespaces,
                        self.embedding_provider.model_id,
                        query_vector,
                        limit=max(limit * 4, 20),
                        mission_id=mission_id,
                        session_id=session_id,
                        valid_at=valid_at,
                        known_at=known_at,
                    )
                    return [
                        row
                        for row in rows
                        if float(row.get("semantic_similarity") or -1.0) >= self.semantic_min_similarity
                    ]
                except TypeError as compat_exc:
                    if "unexpected keyword argument" not in str(compat_exc):
                        raise
                    rows = self.store.semantic_search_pgvector(
                        namespaces,
                        self.embedding_provider.model_id,
                        query_vector,
                        limit=max(limit * 4, 20),
                    )
                    return [
                        row
                        for row in rows
                        if float(row.get("semantic_similarity") or -1.0) >= self.semantic_min_similarity
                    ]
            except Exception as exc:
                # pgvector is the release path. Fallback remains only for pre-cutover/dev compatibility.
                if type(exc).__name__ not in {"UndefinedColumn", "UndefinedObject", "FeatureNotSupported"}:
                    raise
        try:
            rows = self.store.semantic_candidates(
                namespaces,
                self.embedding_provider.model_id,
                limit=5000,
                mission_id=mission_id,
                session_id=session_id,
                valid_at=valid_at,
                known_at=known_at,
            )
        except TypeError as compat_exc:
            if "unexpected keyword argument" not in str(compat_exc):
                raise
            rows = self.store.semantic_candidates(namespaces, self.embedding_provider.model_id, limit=5000)
        scored: list[dict[str, Any]] = []
        for row in rows:
            vector = row.get("embedding")
            if not isinstance(vector, list):
                vector = list(vector or [])
            similarity = self._cosine(query_vector, [float(x) for x in vector])
            item = {k: v for k, v in row.items() if k != "embedding"}
            item["semantic_similarity"] = similarity
            item["retrieval_source"] = "SEMANTIC_FALLBACK"
            if similarity >= self.semantic_min_similarity:
                scored.append(item)
        scored.sort(key=lambda item: float(item.get("semantic_similarity") or -1.0), reverse=True)
        return scored[: max(limit * 4, 20)]

    @staticmethod
    def _merge_candidates(lexical: list[dict[str, Any]], semantic: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        for source_name, rows in (("LEXICAL", lexical), ("SEMANTIC", semantic)):
            for row in rows:
                item_id = str(row["item_id"])
                if item_id not in by_id:
                    by_id[item_id] = dict(row)
                    by_id[item_id]["retrieval_sources"] = [source_name]
                else:
                    current = by_id[item_id]
                    current["retrieval_sources"] = sorted(set(current.get("retrieval_sources", [])) | {source_name})
                    for key in ("text_rank", "semantic_similarity"):
                        if row.get(key) is not None:
                            current[key] = max(float(current.get(key) or 0.0), float(row[key]))
        return list(by_id.values())

    def retrieve(
        self,
        query: str,
        *,
        namespaces: tuple[str, ...],
        limit: int = 8,
        mission_id: str | None = None,
        session_id: str | None = None,
        valid_at: datetime | None = None,
        known_at: datetime | None = None,
    ) -> ContextResult:
        if not query.strip():
            raise ValueError("query obrigatória")
        normalized = [str(ns).strip().upper() for ns in namespaces if str(ns).strip()]
        if not normalized:
            raise ValueError("ao menos um namespace é obrigatório")

        try:
            lexical = self.store.memory_candidates(
                query,
                normalized,
                max(limit * 4, 20),
                mission_id=mission_id,
                session_id=session_id,
                valid_at=valid_at,
                known_at=known_at,
            )
        except TypeError as compat_exc:
            if "unexpected keyword argument" not in str(compat_exc):
                raise
            lexical = self.store.memory_candidates(query, normalized, max(limit * 4, 20))
        for item in lexical:
            item["retrieval_source"] = "LEXICAL"
        semantic = self._semantic_candidates(
            query,
            normalized,
            limit,
            mission_id=mission_id,
            session_id=session_id,
            valid_at=valid_at,
            known_at=known_at,
        )
        candidates = self._merge_candidates(lexical, semantic)
        ranked = sorted(candidates, key=self._score, reverse=True)

        by_key: dict[str, list[dict[str, Any]]] = {}
        for item in ranked:
            by_key.setdefault(str(item["memory_key"]), []).append(item)

        conflicts: list[dict[str, Any]] = []
        selected: list[dict[str, Any]] = []
        for key, rows in by_key.items():
            hashes = {str(row["content_sha256"]) for row in rows}
            if len(hashes) > 1:
                conflicts.append(
                    {
                        "memory_key": key,
                        "items": [
                            {
                                "item_id": row["item_id"],
                                "namespace": row["namespace"],
                                "source": row["source"],
                                "content_sha256": row["content_sha256"],
                                "confidence": row["confidence"],
                            }
                            for row in rows
                        ],
                        "resolution": "EXPLICIT_CONFLICT_NOT_SILENTLY_MERGED",
                    }
                )
            selected.append(rows[0])

        selected = sorted(selected, key=self._score, reverse=True)[: max(1, int(limit))]
        if mission_id:
            try:
                state = self.store.latest_checkpoint(
                    mission_id,
                    normalized,
                    valid_at=valid_at,
                    known_at=known_at,
                )
            except TypeError as compat_exc:
                if "unexpected keyword argument" not in str(compat_exc):
                    raise
                state = self.store.latest_checkpoint(mission_id, normalized)
        else:
            state = None
        modes: list[str] = []
        if lexical:
            modes.append("LEXICAL")
        if semantic:
            modes.append("SEMANTIC")
        if state is not None:
            modes.append("STATE")
        trace_id = self.mutations.record_retrieval_trace(
            query,
            normalized,
            candidates,
            selected,
            conflicts,
            state=state,
            retrieval_modes=modes,
        )
        if self.cognitive_observer is not None:
            try:
                submit = getattr(self.cognitive_observer, "submit_retrieval", None)
                if callable(submit):
                    submit(selected=tuple(selected), trace_id=trace_id)
                else:
                    self.cognitive_observer.observe_retrieval(selected=tuple(selected), trace_id=trace_id)
            except Exception:
                record_failure = getattr(self.cognitive_observer, "record_failure", None)
                if callable(record_failure):
                    record_failure()
                logger.warning(
                    "cognitive shadow observer failed; base retrieval remains authoritative",
                    exc_info=True,
                )
        return ContextResult(
            query=query,
            selected=tuple(selected),
            conflicts=tuple(conflicts),
            trace_id=trace_id,
            state=state,
            retrieval_modes=tuple(modes),
        )
