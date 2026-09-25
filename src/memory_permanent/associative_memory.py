from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

from .association_policy import (
    AssociationLimits,
    AssociationRelation,
    weighted_relation_strength,
)
from .spreading_activation import AssociationNeighbor, AssociationTraversalResult

_KNOWLEDGE_RELATION_MAP: dict[str, AssociationRelation] = {
    "SUPPORTS": AssociationRelation.SUPPORT,
    "REFUTES": AssociationRelation.CONTRADICTION,
    "DERIVED_FROM": AssociationRelation.SHARED_CONTEXT,
    "CORRELATES_WITH": AssociationRelation.CO_OCCURRENCE,
    "CAUSES": AssociationRelation.CAUSAL_RELATION,
    "TESTS": AssociationRelation.SUPPORT,
    "PRODUCES": AssociationRelation.CAUSAL_RELATION,
    "IMPLEMENTS": AssociationRelation.PROCEDURAL_DEPENDENCY,
    "CONSTRAINS": AssociationRelation.PROCEDURAL_DEPENDENCY,
    "ADVANCES": AssociationRelation.SHARED_OBJECTIVE,
    "BASED_ON": AssociationRelation.DECISION_DEPENDENCY,
}

_EXPERIENCE_RELATION_MAP: dict[str, AssociationRelation] = {
    "EVALUATED_BY": AssociationRelation.SUPPORT,
    "INFORMS": AssociationRelation.DECISION_DEPENDENCY,
    "IMPLEMENTED_BY": AssociationRelation.PROCEDURAL_DEPENDENCY,
    "PRODUCES": AssociationRelation.CAUSAL_RELATION,
    "DERIVES": AssociationRelation.SHARED_CONTEXT,
    "CONSOLIDATES": AssociationRelation.SUPPORT,
}


class PostgresAssociationStore:
    """Read canonical graph/vector evidence and persist only shadow association results."""

    def __init__(self, memory_store: Any) -> None:
        self.memory_store = memory_store

    @property
    def tenant_id(self) -> str:
        return str(self.memory_store.tenant_id)

    def _scope_values(self, *, mission_id: str | None, session_id: str | None) -> tuple[str, str, str]:
        access = self.memory_store.access
        return (
            str(access.project_id or ""),
            str(mission_id or ""),
            str(session_id or ""),
        )

    @staticmethod
    def _merge_neighbors(rows: Sequence[AssociationNeighbor], *, limit: int) -> tuple[AssociationNeighbor, ...]:
        merged: dict[tuple[str, str], AssociationNeighbor] = {}
        for edge in rows:
            key = (edge.memory_id, edge.relation_type.value)
            previous = merged.get(key)
            if previous is None or (edge.weight, edge.evidence_strength, edge.source_ref) > (
                previous.weight,
                previous.evidence_strength,
                previous.source_ref,
            ):
                merged[key] = edge
        return tuple(
            sorted(
                merged.values(),
                key=lambda edge: (-edge.weight, edge.memory_id, edge.relation_type.value, edge.source_ref),
            )[: max(1, min(int(limit), 256))]
        )

    def neighbors(
        self,
        memory_id: str,
        *,
        namespaces: Sequence[str],
        mission_id: str | None = None,
        session_id: str | None = None,
        semantic_min_similarity: float = 0.72,
        limit: int = 32,
    ) -> tuple[AssociationNeighbor, ...]:
        item_id = str(memory_id).strip()
        normalized_namespaces = [str(value).strip().upper() for value in namespaces if str(value).strip()]
        if not item_id or not normalized_namespaces:
            return ()
        project_id, mission_scope, session_scope = self._scope_values(mission_id=mission_id, session_id=session_id)
        semantic_threshold = max(0.0, min(1.0, float(semantic_min_similarity)))
        per_source_limit = max(4, min(int(limit), 64))
        output: list[AssociationNeighbor] = []

        with self.memory_store.connection() as conn:
            seed = conn.execute(
                """
                SELECT m.item_id
                FROM memory_items m
                JOIN memory_operator_state s ON s.item_id=m.item_id
                WHERE m.item_id=%s AND m.namespace=ANY(%s)
                  AND memory_scope_matches_context(m.memory_scope,m.memory_scope_ref,%s,%s,%s)
                  AND s.lifecycle_state NOT IN ('PURGED','QUARANTINED')
                """,
                (item_id, normalized_namespaces, project_id, mission_scope, session_scope),
            ).fetchone()
            if not seed:
                return ()

            relation_rows = conn.execute(
                """
                WITH related AS (
                    SELECT r.relation_id,r.relation_type,r.confidence,r.provenance,
                           CASE WHEN r.from_item_id=%s THEN r.to_item_id ELSE r.from_item_id END AS target_item_id
                    FROM memory_knowledge_relations r
                    WHERE r.status='ACTIVE' AND (r.from_item_id=%s OR r.to_item_id=%s)
                )
                SELECT related.relation_id,related.relation_type,related.confidence,related.provenance,
                       related.target_item_id
                FROM related
                JOIN memory_items m ON m.item_id=related.target_item_id
                JOIN memory_operator_state s ON s.item_id=m.item_id
                WHERE m.namespace=ANY(%s)
                  AND memory_scope_matches_context(m.memory_scope,m.memory_scope_ref,%s,%s,%s)
                  AND s.lifecycle_state NOT IN ('PURGED','QUARANTINED')
                ORDER BY related.confidence DESC,related.relation_id
                LIMIT %s
                """,
                (
                    item_id,
                    item_id,
                    item_id,
                    normalized_namespaces,
                    project_id,
                    mission_scope,
                    session_scope,
                    per_source_limit,
                ),
            ).fetchall()
            for row in relation_rows:
                native = str(row["relation_type"])
                relation = _KNOWLEDGE_RELATION_MAP.get(native)
                if relation is None:
                    continue
                confidence = max(0.0, min(1.0, float(row.get("confidence") or 0.0)))
                output.append(
                    AssociationNeighbor(
                        memory_id=str(row["target_item_id"]),
                        relation_type=relation,
                        weight=weighted_relation_strength(relation, observed_strength=confidence),
                        evidence_strength=confidence,
                        source_kind="ONTOLOGY",
                        source_ref=str(row["relation_id"]),
                        evidence={
                            "native_relation": native,
                            "confidence": confidence,
                            "provenance": dict(row.get("provenance") or {}),
                        },
                    )
                )

            graph_params: list[Any] = [item_id, item_id]
            graph_mission_clause = ""
            if mission_id:
                graph_mission_clause = " AND e.mission_id=%s"
                graph_params.append(str(mission_id))
            graph_params.extend(
                [normalized_namespaces, project_id, mission_scope, session_scope, per_source_limit]
            )
            graph_rows = conn.execute(
                f"""
                WITH linked AS (
                    SELECT e.graph_edge_id,e.relation_type,e.evidence,e.mission_id,t.memory_item_id AS target_item_id
                    FROM experience_graph_edges e
                    JOIN experience_graph_nodes f ON f.node_id=e.from_node_id
                    JOIN experience_graph_nodes t ON t.node_id=e.to_node_id
                    WHERE f.memory_item_id=%s AND t.memory_item_id IS NOT NULL
                    UNION ALL
                    SELECT e.graph_edge_id,e.relation_type,e.evidence,e.mission_id,f.memory_item_id AS target_item_id
                    FROM experience_graph_edges e
                    JOIN experience_graph_nodes f ON f.node_id=e.from_node_id
                    JOIN experience_graph_nodes t ON t.node_id=e.to_node_id
                    WHERE t.memory_item_id=%s AND f.memory_item_id IS NOT NULL
                )
                SELECT e.graph_edge_id,e.relation_type,e.evidence,e.mission_id,e.target_item_id
                FROM linked e
                JOIN memory_items m ON m.item_id=e.target_item_id
                JOIN memory_operator_state s ON s.item_id=m.item_id
                WHERE e.target_item_id<>%s
                  {graph_mission_clause}
                  AND m.namespace=ANY(%s)
                  AND memory_scope_matches_context(m.memory_scope,m.memory_scope_ref,%s,%s,%s)
                  AND s.lifecycle_state NOT IN ('PURGED','QUARANTINED')
                ORDER BY e.graph_edge_id
                LIMIT %s
                """,
                tuple([item_id, *graph_params]),
            ).fetchall()
            for row in graph_rows:
                native = str(row["relation_type"])
                relation = _EXPERIENCE_RELATION_MAP.get(native)
                if relation is None:
                    continue
                evidence = dict(row.get("evidence") or {})
                evidence_strength = 1.0 if evidence else 0.60
                output.append(
                    AssociationNeighbor(
                        memory_id=str(row["target_item_id"]),
                        relation_type=relation,
                        weight=weighted_relation_strength(relation, observed_strength=evidence_strength),
                        evidence_strength=evidence_strength,
                        source_kind="EXPERIENCE_GRAPH",
                        source_ref=str(row["graph_edge_id"]),
                        evidence={
                            "native_relation": native,
                            "mission_id": str(row.get("mission_id") or ""),
                            "evidence": evidence,
                        },
                    )
                )

            semantic_rows = conn.execute(
                """
                WITH seed_embedding AS (
                    SELECT e.embedding_vector,e.model_id
                    FROM memory_embeddings e
                    JOIN memory_items m ON m.item_id=e.item_id
                    WHERE e.item_id=%s AND e.status='READY' AND e.embedding_vector IS NOT NULL
                      AND e.content_sha256=m.content_sha256
                    LIMIT 1
                )
                SELECT m.item_id,e.model_id,
                       1 - (e.embedding_vector <=> seed.embedding_vector) AS similarity
                FROM seed_embedding seed
                JOIN memory_embeddings e ON e.model_id=seed.model_id AND e.status='READY' AND e.embedding_vector IS NOT NULL
                JOIN memory_items m ON m.item_id=e.item_id AND e.content_sha256=m.content_sha256
                JOIN memory_operator_state s ON s.item_id=m.item_id
                WHERE m.item_id<>%s
                  AND m.namespace=ANY(%s)
                  AND memory_scope_matches_context(m.memory_scope,m.memory_scope_ref,%s,%s,%s)
                  AND s.lifecycle_state NOT IN ('PURGED','QUARANTINED')
                  AND 1 - (e.embedding_vector <=> seed.embedding_vector) >= %s
                ORDER BY e.embedding_vector <=> seed.embedding_vector,m.item_id
                LIMIT %s
                """,
                (
                    item_id,
                    item_id,
                    normalized_namespaces,
                    project_id,
                    mission_scope,
                    session_scope,
                    semantic_threshold,
                    per_source_limit,
                ),
            ).fetchall()
            for row in semantic_rows:
                similarity = max(0.0, min(1.0, float(row.get("similarity") or 0.0)))
                output.append(
                    AssociationNeighbor(
                        memory_id=str(row["item_id"]),
                        relation_type=AssociationRelation.SEMANTIC_SIMILARITY,
                        weight=weighted_relation_strength(
                            AssociationRelation.SEMANTIC_SIMILARITY,
                            observed_strength=similarity,
                        ),
                        evidence_strength=similarity,
                        source_kind="PGVECTOR",
                        source_ref=f"{item_id}:{row['item_id']}:{row['model_id']}",
                        evidence={"model_id": str(row["model_id"]), "similarity": similarity},
                    )
                )

        return self._merge_neighbors(output, limit=limit)

    def record_traversal_shadow(
        self,
        result: AssociationTraversalResult,
        *,
        retrieval_trace_id: str | None,
        mission_id: str | None,
        session_id: str | None,
    ) -> str:
        traversal_id = f"ast-{uuid.uuid4().hex}"
        project_id, mission_scope, session_scope = self._scope_values(
            mission_id=mission_id,
            session_id=session_id,
        )
        candidates = [candidate.as_dict() for candidate in result.candidates]
        with self.memory_store.connection() as conn:
            conn.execute(
                """
                SELECT memory_record_association_traversal_shadow(
                    %s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s
                )
                """,
                (
                    traversal_id,
                    retrieval_trace_id,
                    list(result.seed_memory_ids),
                    json.dumps(candidates, sort_keys=True),
                    json.dumps(result.deterministic_trace, sort_keys=True),
                    result.policy_version,
                    result.limits.max_depth,
                    result.limits.node_budget,
                    result.limits.time_budget_ms,
                    result.elapsed_ms,
                    project_id,
                    mission_scope,
                    session_scope,
                ),
            )
        return traversal_id

    def load_traversal(self, traversal_id: str) -> dict[str, Any] | None:
        with self.memory_store.connection() as conn:
            row = conn.execute(
                """
                SELECT traversal_id,retrieval_trace_id,seed_memory_ids,candidate_count,visited_count,
                       max_depth,node_budget,time_budget_ms,elapsed_ms,policy_version,deterministic_trace,created_at
                FROM memory_association_traversals WHERE traversal_id=%s
                """,
                (str(traversal_id),),
            ).fetchone()
            if not row:
                return None
            candidates = conn.execute(
                """
                SELECT seed_memory_id,memory_id,relation_type,activation_score,hop_depth,path_jsonb,
                       evidence_strength,evidence_jsonb,source_kind,source_ref,conflict,created_at
                FROM memory_association_candidates WHERE traversal_id=%s
                ORDER BY activation_score DESC,hop_depth,memory_id,association_candidate_id
                """,
                (str(traversal_id),),
            ).fetchall()
        value = dict(row)
        value["created_at"] = value["created_at"].isoformat()
        value["candidates"] = []
        for candidate in candidates:
            item = dict(candidate)
            item["created_at"] = item["created_at"].isoformat()
            value["candidates"].append(item)
        return value


def association_store_spec() -> dict[str, object]:
    limits = AssociationLimits()
    return {
        "mode": "SHADOW",
        "canonical_sources": ["ONTOLOGY", "EXPERIENCE_GRAPH", "PGVECTOR"],
        "persists_inferred_truth": False,
        "persists_traversal_trace": True,
        "default_limits": {
            "max_depth": limits.max_depth,
            "node_budget": limits.node_budget,
            "time_budget_ms": limits.time_budget_ms,
            "max_candidates": limits.max_candidates,
        },
        "native_relation_mappings": {
            "ontology": {key: value.value for key, value in sorted(_KNOWLEDGE_RELATION_MAP.items())},
            "experience_graph": {key: value.value for key, value in sorted(_EXPERIENCE_RELATION_MAP.items())},
        },
        "relation_types": [relation.value for relation in AssociationRelation],
    }
