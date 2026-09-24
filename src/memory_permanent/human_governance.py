from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from .canonical_mutation import CanonicalMutationService, require_canonical_mutation
from .lifecycle_manager import LifecycleManager

HUMAN_GOVERNANCE_CONTRACT = "M17-1.0.0"
DEFAULT_DELETE_QUARANTINE_SECONDS = 86400


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _row(row: Any) -> dict[str, Any]:
    out = dict(row)
    for key, value in list(out.items()):
        out[key] = _iso(value)
    return out


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


class HumanGovernanceManager:
    """V5.1/M17 human governance boundary.

    It never lets the panel purge directly. Human delete requests are
    reference/hold checked, moved to lifecycle quarantine and may be undone
    before a separate privileged purge workflow advances them.
    """

    def __init__(self, store: Any) -> None:
        self.store = store
        self.tenant_id = str(getattr(store, "tenant_id", "LEGACY"))

    def _action(
        self,
        conn: Any,
        *,
        action_type: str,
        actor: str,
        memory_id: str | None = None,
        scope_id: str | None = None,
        reason: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        result: str = "PASS",
        correlation_id: str | None = None,
    ) -> dict[str, str]:
        require_canonical_mutation("human.operator_action")
        action_id = _id("hoa")
        correlation = correlation_id or _id("corr")
        conn.execute(
            """INSERT INTO memory_operator_actions(
                 action_id,tenant_id,memory_id,scope_id,action_type,actor_id,reason,
                 before_state_jsonb,after_state_jsonb,result,correlation_id
               ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                action_id, self.tenant_id, memory_id, scope_id, action_type, actor, reason,
                Jsonb(before or {}), Jsonb(after or {}), result, correlation,
            ),
        )
        if hasattr(self.store, "_audit"):
            self.store._audit(
                conn,
                f"HUMAN_{action_type}",
                memory_id or scope_id,
                {
                    "action_id": action_id,
                    "actor_id": actor,
                    "result": result,
                    "correlation_id": correlation,
                    "reason": reason,
                    "scope_id": scope_id,
                },
            )
        return {"action_id": action_id, "correlation_id": correlation}

    @staticmethod
    def _memory_select() -> str:
        return """
        SELECT
          m.item_id,m.namespace,m.memory_key,m.category,m.content_text,m.content_json,m.provenance,
          m.confidence,m.source,m.source_version,m.tags,m.content_sha256,m.memory_scope,m.memory_scope_ref,
          m.sharing_scope,m.owner_user_id,m.owner_agent_id,m.project_id,m.team_id,m.organization_id,
          m.validation_status,m.governor_eligible,m.occurred_at,m.observed_at,m.valid_from,m.valid_to,
          m.created_at,m.last_used_at,m.retrieval_count,m.application_count,m.success_count,m.failure_count,
          s.operator_class,s.lifecycle_state,s.hold_type,
          d.display_metadata_id,d.display_version,d.human_title,d.human_summary,d.source_context_summary,
          d.topic_tags_jsonb,d.source_kind,d.source_label,d.language,d.review_status,
          ps.scope_id AS project_scope_id,ps.display_name AS project_display_name
        FROM memory_items m
        JOIN memory_operator_state s ON s.item_id=m.item_id
        LEFT JOIN LATERAL(
          SELECT * FROM memory_display_metadata x
          WHERE x.memory_id=m.item_id ORDER BY x.display_version DESC LIMIT 1
        ) d ON true
        LEFT JOIN memory_scopes ps
          ON ps.tenant_id=m.tenant_id AND ps.scope_type='PROJECT'
         AND ps.project_id=COALESCE(m.project_id,CASE WHEN m.memory_scope='PROJECT' THEN m.memory_scope_ref END)
        """

    @staticmethod
    def _human_item(raw: Any) -> dict[str, Any]:
        item = _row(raw)
        apps = int(item.get("application_count") or 0)
        successes = int(item.get("success_count") or 0)
        item["success_rate"] = round(successes * 100 / apps, 2) if apps else None
        item["human_title"] = str(item.get("human_title") or item.get("memory_key") or "Memoria registrada")
        item["human_summary"] = str(item.get("human_summary") or item.get("content_text") or "")[:1200]
        item["source_context_summary"] = str(
            item.get("source_context_summary") or f"Origem: {item.get('source') or 'nao informada'}"
        )[:1200]
        item["scope_type"] = str(item.get("memory_scope") or "GLOBAL_USER")
        item["scope_label"] = (
            "Memorias Gerais" if item["scope_type"] == "GLOBAL_USER"
            else str(item.get("project_display_name") or item.get("memory_scope_ref") or item["scope_type"])
        )
        item["technical_details"] = {
            "item_id": item.get("item_id"),
            "content_sha256": item.get("content_sha256"),
            "namespace": item.get("namespace"),
            "memory_scope_ref": item.get("memory_scope_ref"),
            "project_id": item.get("project_id"),
            "source_version": item.get("source_version"),
        }
        for key in ("content_json", "provenance", "content_sha256", "namespace", "memory_scope_ref"):
            item.pop(key, None)
        return item

    def overview(self) -> dict[str, Any]:
        with self.store.connection() as conn:
            scopes = conn.execute(
                "SELECT scope_type,count(*) AS n FROM memory_scopes GROUP BY scope_type ORDER BY scope_type"
            ).fetchall()
            memories = conn.execute(
                "SELECT memory_scope,count(*) AS n FROM memory_items GROUP BY memory_scope ORDER BY memory_scope"
            ).fetchall()
            projects = conn.execute(
                "SELECT count(*) AS n FROM memory_scopes WHERE scope_type='PROJECT' AND status='ACTIVE'"
            ).fetchone()
            deletes = conn.execute(
                "SELECT state,count(*) AS n FROM memory_delete_requests GROUP BY state ORDER BY state"
            ).fetchall()
            promotions = conn.execute("SELECT count(*) AS n FROM memory_scope_promotions").fetchone()
            manifests = conn.execute(
                "SELECT count(*) AS n,count(*) FILTER(WHERE verification_state='FAILED') AS failed "
                "FROM integrity_manifests"
            ).fetchone()
        return {
            "contract": HUMAN_GOVERNANCE_CONTRACT,
            "health": "OK",
            "scope_registry": {str(r["scope_type"]): int(r["n"]) for r in scopes},
            "memory_distribution": {str(r["memory_scope"]): int(r["n"]) for r in memories},
            "projects_total": int(projects["n"] or 0),
            "delete_states": {str(r["state"]): int(r["n"]) for r in deletes},
            "scope_promotions_total": int(promotions["n"] or 0),
            "integrity_manifests": {
                "total": int(manifests["n"] or 0),
                "failed": int(manifests["failed"] or 0),
            },
            "direct_purge_from_panel": False,
        }

    def scopes(self) -> dict[str, Any]:
        with self.store.connection() as conn:
            rows = conn.execute(
                """SELECT scope_id,scope_type,parent_scope_id,user_id,project_id,mission_id,session_id,
                          display_name,status,created_at,updated_at
                   FROM memory_scopes ORDER BY scope_type,display_name,scope_id"""
            ).fetchall()
        items = [_row(r) for r in rows]
        by_parent: dict[str | None, list[dict[str, Any]]] = {}
        for item in items:
            by_parent.setdefault(item.get("parent_scope_id"), []).append(item)

        def node(item: dict[str, Any]) -> dict[str, Any]:
            return {**item, "children": [node(c) for c in by_parent.get(item["scope_id"], [])]}

        return {
            "contract": HUMAN_GOVERNANCE_CONTRACT,
            "items": items,
            "tree": [node(i) for i in items if not i.get("parent_scope_id")],
        }

    def _list_memories(
        self,
        *,
        scope: str | None = None,
        project_id: str | None = None,
        query: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses = ["s.lifecycle_state<>'PURGED'"]
        params: list[Any] = []
        if scope:
            clauses.append("m.memory_scope=%s")
            params.append(str(scope).upper())
        if project_id:
            clauses.append(
                "COALESCE(m.project_id,CASE WHEN m.memory_scope='PROJECT' THEN m.memory_scope_ref END)=%s"
            )
            params.append(str(project_id))
        if query and str(query).strip():
            q = f"%{str(query).strip()}%"
            clauses.append(
                "(d.human_title ILIKE %s OR d.human_summary ILIKE %s OR "
                "d.source_context_summary ILIKE %s OR ps.display_name ILIKE %s OR "
                "m.memory_key ILIKE %s OR m.content_text ILIKE %s OR m.source ILIKE %s)"
            )
            params.extend([q] * 7)
        params.append(min(max(int(limit), 1), 500))
        sql = self._memory_select() + " WHERE " + " AND ".join(clauses) + (
            " ORDER BY COALESCE(m.last_used_at,m.created_at) DESC LIMIT %s"
        )
        with self.store.connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._human_item(r) for r in rows]

    def global_memories(self, *, query: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        return self._list_memories(scope="GLOBAL_USER", query=query, limit=limit)

    def projects(self) -> list[dict[str, Any]]:
        with self.store.connection() as conn:
            rows = conn.execute(
                """SELECT s.scope_id,s.project_id,s.display_name,s.status,count(m.item_id) AS memory_count,
                          max(m.created_at) AS latest_memory_at
                   FROM memory_scopes s
                   LEFT JOIN memory_items m ON m.tenant_id=s.tenant_id
                    AND COALESCE(m.project_id,CASE WHEN m.memory_scope='PROJECT' THEN m.memory_scope_ref END)=s.project_id
                   WHERE s.scope_type='PROJECT'
                   GROUP BY s.scope_id,s.project_id,s.display_name,s.status
                   ORDER BY s.display_name"""
            ).fetchall()
        return [_row(r) for r in rows]

    def project_memories(
        self, project_id: str, *, query: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        return self._list_memories(project_id=project_id, query=query, limit=limit)

    @staticmethod
    def _dependency_check(conn: Any, item_id: str) -> dict[str, Any]:
        blockers: list[dict[str, Any]] = []
        for r in conn.execute(
            """SELECT a.artifact_type,a.artifact_ref,a.status
               FROM memory_artifact_dependencies d
               JOIN memory_derived_artifacts a ON a.artifact_id=d.artifact_id
               WHERE d.source_item_id=%s AND a.status='READY'
               ORDER BY a.artifact_type,a.artifact_ref LIMIT 100""",
            (item_id,),
        ).fetchall():
            blockers.append(
                {
                    "kind": "DERIVED_ARTIFACT",
                    "label": f"{r['artifact_type']} - {r['artifact_ref']}",
                    "ref": r["artifact_ref"],
                }
            )
        queries = (
            (
                "SELECT decision_id AS ref FROM sovereign_decision_evidence WHERE item_id=%s LIMIT 50",
                (item_id,),
                "DECISION_EVIDENCE",
                "Decisao",
            ),
            (
                "SELECT mission_id||':'||node_id AS ref FROM experience_graph_nodes "
                "WHERE memory_item_id=%s LIMIT 50",
                (item_id,),
                "MISSION_GRAPH",
                "Missao",
            ),
            (
                "SELECT relation_id AS ref FROM memory_knowledge_relations "
                "WHERE from_item_id=%s OR to_item_id=%s LIMIT 50",
                (item_id, item_id),
                "KNOWLEDGE_RELATION",
                "Relacao",
            ),
            (
                "SELECT assessment_id AS ref FROM memory_causal_assessments WHERE item_id=%s LIMIT 50",
                (item_id,),
                "CAUSAL_EVIDENCE",
                "Evidencia causal",
            ),
        )
        for sql, params, kind, label in queries:
            try:
                for r in conn.execute(sql, params).fetchall():
                    blockers.append(
                        {"kind": kind, "label": f"{label} - {r['ref']}", "ref": r["ref"]}
                    )
            except Exception as exc:
                if type(exc).__name__ not in {"UndefinedTable", "UndefinedColumn"}:
                    raise
        return {"blocked": bool(blockers), "count": len(blockers), "blockers": blockers[:200]}

    @staticmethod
    def _hold_check(conn: Any, item_id: str) -> dict[str, Any]:
        rows = conn.execute(
            "SELECT hold_id,hold_type,reason,created_at FROM retention_holds "
            "WHERE item_id=%s AND status='ACTIVE' ORDER BY created_at",
            (item_id,),
        ).fetchall()
        holds = [_row(r) for r in rows]
        return {"blocked": bool(holds), "count": len(holds), "holds": holds}

    @staticmethod
    def _blocked_message(dep: dict[str, Any], hold: dict[str, Any]) -> str:
        if hold.get("blocked"):
            labels = [str(x.get("hold_type") or x.get("hold_id")) for x in hold["holds"][:4]]
            return "Nao pode ser excluida agora. Protecao ativa: " + ", ".join(labels) + "."
        labels = [str(x.get("label") or x.get("ref")) for x in dep.get("blockers", [])[:6]]
        return "Nao pode ser excluida agora. Usada por: " + ", ".join(labels) + "."

    def operator_view(self, item_id: str) -> dict[str, Any]:
        with self.store.connection() as conn:
            raw = conn.execute(self._memory_select() + " WHERE m.item_id=%s", (item_id,)).fetchone()
            if not raw:
                raise KeyError(item_id)
            holds = conn.execute(
                "SELECT hold_id,hold_type,reason,status,created_at FROM retention_holds "
                "WHERE item_id=%s ORDER BY created_at DESC",
                (item_id,),
            ).fetchall()
            deps = self._dependency_check(conn, item_id)
            latest_delete = conn.execute(
                "SELECT * FROM memory_delete_requests WHERE memory_id=%s "
                "ORDER BY requested_at DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            actions = conn.execute(
                "SELECT action_id,action_type,actor_id,reason,result,correlation_id,created_at "
                "FROM memory_operator_actions WHERE memory_id=%s ORDER BY created_at DESC LIMIT 50",
                (item_id,),
            ).fetchall()
        return {
            "contract": HUMAN_GOVERNANCE_CONTRACT,
            "memory": self._human_item(raw),
            "protection": {"holds": [_row(r) for r in holds], "dependency_check": deps},
            "latest_delete_request": _row(latest_delete) if latest_delete else None,
            "operator_actions": [_row(r) for r in actions],
        }

    def update_display_metadata(
        self,
        *,
        item_id: str,
        actor: str,
        human_title: str | None = None,
        human_summary: str | None = None,
        source_context_summary: str | None = None,
        topic_tags: list[str] | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        require_canonical_mutation("human.display_metadata")
        with self.store.connection() as conn:
            current = conn.execute(
                "SELECT * FROM memory_display_metadata WHERE memory_id=%s "
                "ORDER BY display_version DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            memory = conn.execute(
                "SELECT source,category,tags FROM memory_items WHERE item_id=%s", (item_id,)
            ).fetchone()
            if not memory:
                raise KeyError(item_id)
            if not current:
                raise RuntimeError("human display metadata missing")
            title = str(human_title if human_title is not None else current["human_title"]).strip()
            summary = str(
                human_summary if human_summary is not None else current["human_summary"]
            ).strip()
            context = (
                source_context_summary
                if source_context_summary is not None
                else current["source_context_summary"]
            )
            if not title or not summary:
                raise ValueError("human_title and human_summary are required")
            display_id = _id("dmeta")
            conn.execute(
                """INSERT INTO memory_display_metadata(
                     display_metadata_id,tenant_id,memory_id,display_version,human_title,human_summary,
                     source_context_summary,topic_tags_jsonb,source_kind,source_label,language,generated_by,
                     review_status,supersedes_display_metadata_id
                   ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pt-BR',%s,'OPERATOR_EDITED',%s)""",
                (
                    display_id,self.tenant_id,item_id,int(current["display_version"])+1,
                    title[:300],summary[:1200],str(context)[:1200] if context else None,
                    Jsonb(topic_tags if topic_tags is not None else list(current["topic_tags_jsonb"] or [])),
                    str(current["source_kind"] or memory["category"]),
                    str(current["source_label"] or memory["source"]),
                    actor,str(current["display_metadata_id"]),
                ),
            )
            after = dict(
                conn.execute(
                    "SELECT * FROM memory_display_metadata WHERE display_metadata_id=%s",
                    (display_id,),
                ).fetchone()
            )
            self._action(
                conn,
                action_type="RENAME_DISPLAY_TITLE" if human_title is not None else "EDIT_DISPLAY_SUMMARY",
                actor=actor,
                memory_id=item_id,
                reason=reason,
                before=_row(current),
                after=after,
            )
            return _row(after)

    def classify(
        self,
        *,
        item_id: str,
        operator_class: str,
        actor: str,
        action_type: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        require_canonical_mutation("human.classify")
        with self.store.connection() as conn:
            before = conn.execute(
                "SELECT * FROM memory_operator_state WHERE item_id=%s", (item_id,)
            ).fetchone()
        result = CanonicalMutationService(self.store, actor_id=actor).classify([item_id], operator_class, actor_id=actor)
        with self.store.connection() as conn:
            after = conn.execute(
                "SELECT * FROM memory_operator_state WHERE item_id=%s", (item_id,)
            ).fetchone()
            self._action(
                conn,
                action_type=action_type,
                actor=actor,
                memory_id=item_id,
                reason=reason,
                before=_row(before) if before else {},
                after=_row(after) if after else {},
            )
        return result

    def protect(self, *, item_id: str, actor: str, reason: str | None = None) -> dict[str, Any]:
        return self.classify(
            item_id=item_id,
            operator_class="PROTEGIDA",
            actor=actor,
            action_type="PROTECT_HOLD",
            reason=reason,
        )

    def archive(self, *, item_id: str, actor: str, reason: str | None = None) -> dict[str, Any]:
        return self.classify(
            item_id=item_id,
            operator_class="ARQUIVADA",
            actor=actor,
            action_type="ARCHIVE",
            reason=reason,
        )

    def delete_memory(
        self,
        *,
        item_id: str,
        actor: str,
        reason: str,
        idempotency_key: str,
        quarantine_seconds: int = DEFAULT_DELETE_QUARANTINE_SECONDS,
    ) -> dict[str, Any]:
        require_canonical_mutation("human.delete")
        key = str(idempotency_key or "").strip()
        if not key or len(key) > 240:
            raise ValueError("valid idempotency_key is required")
        window = min(max(int(quarantine_seconds), 60), 604800)
        correlation = _id("corr")
        with self.store.connection() as conn:
            existing = conn.execute(
                "SELECT * FROM memory_delete_requests WHERE tenant_id=%s AND idempotency_key=%s",
                (self.tenant_id, key),
            ).fetchone()
            if existing:
                result = _row(existing)
                result["idempotent_replay"] = True
                return result
            if not conn.execute(
                "SELECT 1 FROM memory_items WHERE item_id=%s", (item_id,)
            ).fetchone():
                raise KeyError(item_id)
            before = conn.execute(
                "SELECT * FROM memory_operator_state WHERE item_id=%s", (item_id,)
            ).fetchone()
            delete_id = _id("del")
            conn.execute(
                """INSERT INTO memory_delete_requests(
                     delete_request_id,tenant_id,memory_id,requested_by,state,before_state_jsonb,
                     idempotency_key,correlation_id
                   ) VALUES(%s,%s,%s,%s,'REQUESTED',%s,%s,%s)""",
                (
                    delete_id,self.tenant_id,item_id,actor,
                    Jsonb(_row(before) if before else {}),key,correlation,
                ),
            )
            self._action(
                conn,
                action_type="DELETE_REQUESTED",
                actor=actor,
                memory_id=item_id,
                reason=reason,
                before=_row(before) if before else {},
                after={"delete_request_id": delete_id, "state": "REQUESTED"},
                correlation_id=correlation,
            )
            conn.execute(
                "UPDATE memory_delete_requests SET state='VALIDATING' WHERE delete_request_id=%s",
                (delete_id,),
            )
            dep = self._dependency_check(conn, item_id)
            hold = self._hold_check(conn, item_id)
            if hold["blocked"] or dep["blocked"]:
                state = "BLOCKED_HOLD" if hold["blocked"] else "BLOCKED_DEPENDENCY"
                message = self._blocked_message(dep, hold)
                conn.execute(
                    """UPDATE memory_delete_requests
                       SET state=%s,dependency_check_jsonb=%s,hold_check_jsonb=%s,
                           blocked_reason=%s,completed_at=now()
                       WHERE delete_request_id=%s""",
                    (state, Jsonb(dep), Jsonb(hold), message, delete_id),
                )
                self._action(
                    conn,
                    action_type="DELETE_BLOCKED",
                    actor=actor,
                    memory_id=item_id,
                    reason=message,
                    before=_row(before) if before else {},
                    after={"delete_request_id": delete_id, "state": state},
                    result="BLOCKED",
                    correlation_id=correlation,
                )
                result = dict(
                    conn.execute(
                        "SELECT * FROM memory_delete_requests WHERE delete_request_id=%s",
                        (delete_id,),
                    ).fetchone()
                )
                result["human_message"] = message
                return _row(result)

        CanonicalMutationService(self.store, actor_id=actor).classify([item_id], "DESCARTAVEL", actor_id=actor)
        lifecycle = LifecycleManager(self.store)
        request = lifecycle.request_purge(
            item_id=item_id,
            reason=reason,
            recovery_window_seconds=window,
            evidence={"human_delete_request": delete_id, "correlation_id": correlation},
            actor=actor,
        )
        quarantine = lifecycle.quarantine(
            request_id=str(request["request_id"]),
            evidence={"human_delete_request": delete_id, "correlation_id": correlation},
            actor=actor,
        )
        until = datetime.now(UTC) + timedelta(seconds=window)
        with self.store.connection() as conn:
            conn.execute(
                """UPDATE memory_delete_requests
                   SET state='QUARANTINED',dependency_check_jsonb=%s,hold_check_jsonb=%s,
                       quarantine_until=%s,lifecycle_request_id=%s
                   WHERE delete_request_id=%s""",
                (
                    Jsonb(dep),Jsonb(hold),until,str(request["request_id"]),delete_id,
                ),
            )
            self._action(
                conn,
                action_type="DELETE_QUARANTINED",
                actor=actor,
                memory_id=item_id,
                reason=reason,
                before={"delete_request_id": delete_id, "state": "VALIDATING"},
                after={
                    "state": "QUARANTINED",
                    "lifecycle_request_id": str(request["request_id"]),
                    "quarantine_until": until.isoformat(),
                },
                correlation_id=correlation,
            )
            result = dict(
                conn.execute(
                    "SELECT * FROM memory_delete_requests WHERE delete_request_id=%s",
                    (delete_id,),
                ).fetchone()
            )
        result["lifecycle"] = _row(quarantine)
        result["human_message"] = (
            "Memoria em quarentena. A exclusao pode ser desfeita antes do purge governado."
        )
        return _row(result)

    def undo_delete(self, *, item_id: str, actor: str, reason: str) -> dict[str, Any]:
        require_canonical_mutation("human.undo_delete")
        with self.store.connection() as conn:
            request = conn.execute(
                """SELECT * FROM memory_delete_requests
                   WHERE memory_id=%s AND state='QUARANTINED'
                   ORDER BY requested_at DESC LIMIT 1 FOR UPDATE""",
                (item_id,),
            ).fetchone()
            if not request:
                raise ValueError("no quarantined delete request found")
            before_state = _mapping(request["before_state_jsonb"])
            lifecycle_id = str(request["lifecycle_request_id"] or "")
            conn.execute("SELECT set_config('app.lifecycle_mutation_authorized','1',true)")
            if lifecycle_id:
                lifecycle = conn.execute(
                    "SELECT status FROM lifecycle_requests WHERE request_id=%s FOR UPDATE",
                    (lifecycle_id,),
                ).fetchone()
                if not lifecycle or str(lifecycle["status"]) != "QUARANTINED":
                    raise ValueError("delete can only be undone while lifecycle is QUARANTINED")
                conn.execute(
                    "UPDATE lifecycle_requests SET status='CANCELLED' WHERE request_id=%s",
                    (lifecycle_id,),
                )
                conn.execute(
                    """UPDATE lifecycle_recovery_snapshots
                       SET status='DESTROYED',payload_json='{}'::jsonb,destroyed_at=now()
                       WHERE request_id=%s AND status='ACTIVE'""",
                    (lifecycle_id,),
                )
            conn.execute(
                """UPDATE memory_operator_state
                   SET operator_class=%s,lifecycle_state=%s,hold_type=%s,changed_by=%s,changed_at=now()
                   WHERE item_id=%s""",
                (
                    str(before_state.get("operator_class") or "ATIVA"),
                    str(before_state.get("lifecycle_state") or "HOT"),
                    before_state.get("hold_type"),
                    actor,
                    item_id,
                ),
            )
            conn.execute(
                "UPDATE memory_delete_requests SET state='UNDONE',completed_at=now() "
                "WHERE delete_request_id=%s",
                (request["delete_request_id"],),
            )
            self._action(
                conn,
                action_type="DELETE_UNDONE",
                actor=actor,
                memory_id=item_id,
                reason=reason,
                before={"state": "QUARANTINED", "lifecycle_request_id": lifecycle_id},
                after={
                    "state": "UNDONE",
                    "operator_class": str(before_state.get("operator_class") or "ATIVA"),
                },
                correlation_id=str(request["correlation_id"]),
            )
            result = dict(
                conn.execute(
                    "SELECT * FROM memory_delete_requests WHERE delete_request_id=%s",
                    (request["delete_request_id"],),
                ).fetchone()
            )
        result["human_message"] = "Exclusao desfeita. O conteudo canonico permaneceu preservado."
        return _row(result)

    def delete_batch(
        self,
        *,
        item_ids: list[str],
        actor: str,
        reason: str,
        idempotency_key: str,
        quarantine_seconds: int = DEFAULT_DELETE_QUARANTINE_SECONDS,
    ) -> dict[str, Any]:
        unique = list(dict.fromkeys(str(x) for x in item_ids if str(x).strip()))[:500]
        if not unique:
            raise ValueError("at least one memory is required")
        results: list[dict[str, Any]] = []
        for index, item_id in enumerate(unique):
            try:
                value = self.delete_memory(
                    item_id=item_id,
                    actor=actor,
                    reason=reason,
                    idempotency_key=f"{idempotency_key}:{index}:{item_id}",
                    quarantine_seconds=quarantine_seconds,
                )
                results.append({"item_id": item_id, "ok": True, "result": value})
            except Exception as exc:  # noqa: BLE001 -- isolate per-item batch failures
                results.append(
                    {
                        "item_id": item_id,
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                    }
                )
        return {
            "contract": HUMAN_GOVERNANCE_CONTRACT,
            "requested": len(unique),
            "succeeded": sum(1 for x in results if x["ok"]),
            "failed": sum(1 for x in results if not x["ok"]),
            "items": results,
            "partial_failure_isolated": True,
        }

    def promote_project_to_global(
        self,
        *,
        item_id: str,
        actor: str,
        reason: str,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        require_canonical_mutation("human.promote_scope")
        if not str(reason or "").strip():
            raise ValueError("promotion reason is required")
        with self.store.connection() as conn:
            src = conn.execute(
                "SELECT * FROM memory_items WHERE item_id=%s FOR SHARE", (item_id,)
            ).fetchone()
            if not src:
                raise KeyError(item_id)
            if str(src["memory_scope"]) != "PROJECT":
                raise ValueError("only PROJECT memory can be promoted to GLOBAL_USER")
            version = conn.execute(
                "SELECT version_id,version_no,content_sha256 FROM memory_versions "
                "WHERE item_id=%s ORDER BY version_no DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            provenance = _mapping(src["provenance"])
            provenance = {
                **provenance,
                "scope_promotion": {
                    "contract": HUMAN_GOVERNANCE_CONTRACT,
                    "source_item_id": item_id,
                    "source_scope": "PROJECT",
                    "source_scope_ref": src["memory_scope_ref"],
                    "source_version_id": version["version_id"] if version else None,
                    "actor_id": actor,
                    "reason": reason,
                    "evidence": evidence or {},
                },
            }

        promoted_id = CanonicalMutationService(self.store, actor_id=actor).remember_internal(
            actor_id=actor,
            source=str(src["source"]),
            provenance=provenance,
            trusted=False,
            namespace=str(src["namespace"]),
            memory_key=str(src["memory_key"]),
            category=str(src["category"]),
            content=dict(src["content_json"]),
            content_text=str(src["content_text"]),
            confidence=float(src["confidence"]),
            source_version=str(src["source_version"]) if src["source_version"] else None,
            tags=list(src["tags"] or []),
            supersedes_id=None,
            memory_scope="GLOBAL_USER",
            memory_scope_ref=None,
            sharing_scope=str(src["sharing_scope"]),
            owner_user_id=src["owner_user_id"],
            owner_agent_id=src["owner_agent_id"],
            project_id=None,
            team_id=src["team_id"],
            organization_id=src["organization_id"],
        )
        promotion_id = _id("prom")
        with self.store.connection() as conn:
            conn.execute(
                """INSERT INTO memory_scope_promotions(
                     promotion_id,tenant_id,source_memory_id,promoted_memory_id,
                     from_scope,from_scope_ref,to_scope,actor_id,reason,source_version_id,evidence_jsonb
                   ) VALUES(%s,%s,%s,%s,'PROJECT',%s,'GLOBAL_USER',%s,%s,%s,%s)""",
                (
                    promotion_id,self.tenant_id,item_id,promoted_id,src["memory_scope_ref"],
                    actor,reason,version["version_id"] if version else None,Jsonb(evidence or {}),
                ),
            )
            action = self._action(
                conn,
                action_type="PROMOTE_SCOPE",
                actor=actor,
                memory_id=item_id,
                reason=reason,
                before={
                    "scope": "PROJECT",
                    "scope_ref": src["memory_scope_ref"],
                    "source_version_id": version["version_id"] if version else None,
                },
                after={"scope": "GLOBAL_USER", "promoted_memory_id": promoted_id},
            )
        return {
            "contract": HUMAN_GOVERNANCE_CONTRACT,
            "promotion_id": promotion_id,
            "source_memory_id": item_id,
            "promoted_memory_id": promoted_id,
            "from_scope": "PROJECT",
            "to_scope": "GLOBAL_USER",
            "actor_id": actor,
            "reason": reason,
            "source_version_id": version["version_id"] if version else None,
            "silent_promotion": False,
            **action,
        }

    def report_markdown(self) -> str:
        overview = self.overview()
        projects = self.projects()
        with self.store.connection() as conn:
            promotions = conn.execute(
                """SELECT source_memory_id,promoted_memory_id,actor_id,reason,created_at
                   FROM memory_scope_promotions ORDER BY created_at DESC LIMIT 20"""
            ).fetchall()
            manifest = conn.execute(
                """SELECT manifest_id,root_hash,verification_state,external_anchor_ref,anchored_at
                   FROM integrity_manifests ORDER BY created_at DESC LIMIT 1"""
            ).fetchone()
        lines = [
            "# Relatorio Operacional - Memoria Permanente",
            "",
            f"- Contrato humano: `{HUMAN_GOVERNANCE_CONTRACT}`",
            f"- Saude: `{overview['health']}`",
            f"- Memorias gerais: `{overview['memory_distribution'].get('GLOBAL_USER', 0)}`",
            f"- Projetos: `{overview['projects_total']}`",
            f"- Promocoes explicitas: `{overview['scope_promotions_total']}`",
            "- Purge direto pelo painel: `False`",
            "",
            "## Memorias por escopo",
        ]
        for key, value in sorted(overview["memory_distribution"].items()):
            lines.append(f"- {key}: `{value}`")
        lines.extend(["", "## Projetos"])
        for project in projects:
            lines.append(f"- {project['display_name']}: `{project['memory_count']}` memorias")
        lines.extend(["", "## Exclusoes"])
        for state, value in sorted(overview["delete_states"].items()):
            lines.append(f"- {state}: `{value}`")
        lines.extend(["", "## Promocoes recentes"])
        for row in promotions:
            lines.append(
                f"- `{row['source_memory_id']}` -> `{row['promoted_memory_id']}` "
                f"por `{row['actor_id']}`: {row['reason']}"
            )
        lines.extend(["", "## Integridade"])
        if manifest:
            lines.append(
                f"- Ultimo manifesto: `{manifest['manifest_id']}` - `{manifest['verification_state']}`"
            )
            lines.append(f"- Ancora externa: `{manifest['external_anchor_ref']}`")
            lines.append(f"- Root hash: `{manifest['root_hash']}`")
        else:
            lines.append("- Nenhum manifesto registrado.")
        lines.append("")
        return "\n".join(lines)

