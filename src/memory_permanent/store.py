from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg import sql as pg_sql
from psycopg.rows import dict_row

from .access_policy import AgentAccessContext
from .canonical_mutation import require_canonical_mutation
from .causal_policy import CAUSAL_POLICY_VERSION, evaluate_causal_assessment
from .decision_memory import (
    DECISION_RECORD_VERSION,
    build_replay_package,
    decision_core_material,
    validate_decision_record,
)
from .domain import map_operator_class
from .economic_memory import (
    validate_entity_record,
    validate_result_record,
    validate_state_record,
)
from .experience_graph import (
    normalize_node_type,
    reconstruct_mission_graph,
    validate_edge_rule,
    validate_memory_binding,
)
from .learning_policy import POLICY_VERSION, LearningPolicyEngine
from .migration_runner import apply_migrations, default_migrations_dir, migration_status
from .ontology import normalize_knowledge_type, validate_relation, validate_transition
from .operational_memory import (
    validate_capability_record,
    validate_competency_record,
    validate_proof_record,
    validate_skill_record,
    validate_skill_version_record,
    validate_status_record,
)
from .temporal import normalize_as_of, normalize_temporal_envelope


def now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def idempotency_temporal_request(*, occurred_at: datetime | None, observed_at: datetime | None, valid_from: datetime | None, valid_to: datetime | None) -> dict[str, str | None]:
    """Stable client-request temporal envelope for idempotency hashing.

    Server-assigned temporal defaults must never enter the idempotency hash: a
    retry of the same request with omitted timestamps must hash identically.
    """
    return {
        "occurred_at": occurred_at.isoformat() if occurred_at is not None else None,
        "observed_at": observed_at.isoformat() if observed_at is not None else None,
        "valid_from": valid_from.isoformat() if valid_from is not None else None,
        "valid_to": valid_to.isoformat() if valid_to is not None else None,
    }


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS schema_meta(
  key text PRIMARY KEY,
  value text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_meta(key,value) VALUES('schema_version','memory-0.1.0')
ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=now();

CREATE TABLE IF NOT EXISTS memory_items(
  item_id text PRIMARY KEY,
  namespace text NOT NULL,
  memory_key text NOT NULL,
  category text NOT NULL DEFAULT 'FACT',
  content_json jsonb NOT NULL,
  content_text text NOT NULL,
  provenance jsonb NOT NULL,
  confidence double precision NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
  source text NOT NULL,
  source_version text,
  tags text[] NOT NULL DEFAULT '{}',
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_until timestamptz,
  supersedes_id text,
  content_sha256 text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz,
  retrieval_count bigint NOT NULL DEFAULT 0,
  application_count bigint NOT NULL DEFAULT 0,
  success_count bigint NOT NULL DEFAULT 0,
  failure_count bigint NOT NULL DEFAULT 0,
  search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple',coalesce(content_text,''))) STORED
);
CREATE INDEX IF NOT EXISTS idx_memory_key_ns ON memory_items(memory_key,namespace,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_fts ON memory_items USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_memory_tags ON memory_items USING GIN(tags);

CREATE TABLE IF NOT EXISTS memory_operator_state(
  item_id text PRIMARY KEY REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  operator_class text NOT NULL CHECK(operator_class IN ('PERMANENTE','ATIVA','ARQUIVADA','DESCARTÁVEL','PROTEGIDA')),
  lifecycle_state text NOT NULL CHECK(lifecycle_state IN ('HOT','WARM','COLD','DELETE_ELIGIBLE','QUARANTINED','PURGED')),
  hold_type text,
  changed_by text NOT NULL,
  changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS retention_holds(
  hold_id text PRIMARY KEY,
  item_id text NOT NULL REFERENCES memory_items(item_id) ON DELETE RESTRICT,
  hold_type text NOT NULL,
  reason text NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  released_at timestamptz,
  status text NOT NULL CHECK(status IN ('ACTIVE','RELEASED')) DEFAULT 'ACTIVE'
);
CREATE INDEX IF NOT EXISTS idx_retention_holds_item ON retention_holds(item_id,status);

CREATE TABLE IF NOT EXISTS retrieval_traces(
  trace_id text PRIMARY KEY,
  query_text text NOT NULL,
  namespaces text[] NOT NULL,
  candidates jsonb NOT NULL,
  selected jsonb NOT NULL,
  conflicts jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS checkpoints(
  checkpoint_id text PRIMARY KEY,
  namespace text NOT NULL,
  mission_id text NOT NULL,
  step_index integer NOT NULL,
  state_json jsonb NOT NULL,
  state_sha256 text NOT NULL,
  created_at timestamptz NOT NULL,
  migration_source text
);
CREATE INDEX IF NOT EXISTS idx_memory_checkpoints_mission ON checkpoints(mission_id,step_index);

CREATE TABLE IF NOT EXISTS legacy_security_audit(
  legacy_seq bigint PRIMARY KEY,
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  previous_hash text NOT NULL,
  event_hash text NOT NULL,
  created_at timestamptz NOT NULL,
  migration_source text NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events(
  seq bigserial PRIMARY KEY,
  event_type text NOT NULL,
  target_id text,
  payload jsonb NOT NULL,
  previous_hash text NOT NULL,
  event_hash text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL
);
"""


class IdempotencyConflict(RuntimeError):
    pass


class ConcurrencyConflict(RuntimeError):
    pass


class PostgresMemoryStore:
    """Persistência soberana exclusiva do domínio de memória."""

    def __init__(
        self,
        dsn: str,
        *,
        initialize: bool = True,
        tenant_id: str = "LEGACY",
        access: AgentAccessContext | None = None,
    ) -> None:
        self.dsn = dsn
        tenant = str(tenant_id or "").strip().upper()
        if not tenant or len(tenant) > 120 or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-:." for ch in tenant):
            raise ValueError("invalid tenant_id")
        self.tenant_id = tenant
        self.access = access or AgentAccessContext.build()
        if initialize:
            self.initialize()

    @contextmanager
    def connection(self):
        """Public transactional connection boundary with tenant/access context applied."""
        conn = psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5)
        try:
            with conn.transaction():
                settings = {
                    "app.current_tenant": self.tenant_id,
                    "app.current_agent": self.access.agent_id or "",
                    "app.current_user_id": self.access.user_id or "",
                    "app.current_project": self.access.project_id or "",
                    "app.current_team": self.access.team_id or "",
                    "app.current_org": self.access.organization_id or "",
                }
                for key, value in settings.items():
                    conn.execute("SELECT set_config(%s, %s, true)", (key, value))
                yield conn
        finally:
            conn.close()

    @contextmanager
    def _connection(self):
        """Backward-compatible internal alias; external modules must use connection()."""
        with self.connection() as conn:
            yield conn

    def initialize(self) -> None:
        apply_migrations(self.dsn, default_migrations_dir())

    def migrations(self) -> list[dict[str, Any]]:
        return migration_status(self.dsn)

    def _audit(self, conn, event_type: str, target_id: str | None, payload: dict[str, Any]) -> str:
        require_canonical_mutation("audit.append")
        ts = datetime.now(UTC)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('memory.audit.chain'))")
        prev = conn.execute("SELECT event_hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = str(prev["event_hash"]) if prev else "0" * 64
        digest = hashlib.sha256((previous + canonical(payload) + event_type + ts.isoformat()).encode()).hexdigest()
        conn.execute(
            "INSERT INTO audit_events(event_type,target_id,payload,previous_hash,event_hash,created_at) VALUES(%s,%s,%s::jsonb,%s,%s,%s)",
            (event_type, target_id, canonical(payload), previous, digest, ts),
        )
        return digest

    def _idempotency_replay(
        self, conn, *, operation: str, idempotency_key: str | None, request_sha256: str
    ) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        row = conn.execute(
            "SELECT request_sha256,response_json FROM idempotency_records WHERE operation=%s AND idempotency_key=%s",
            (operation, idempotency_key),
        ).fetchone()
        if not row:
            return None
        if str(row["request_sha256"]) != request_sha256:
            raise IdempotencyConflict(f"idempotency key reused with different payload for {operation}")
        return dict(row["response_json"])

    def _idempotency_store(
        self, conn, *, operation: str, idempotency_key: str | None, request_sha256: str, response: dict[str, Any]
    ) -> None:
        require_canonical_mutation("idempotency.store")
        if not idempotency_key:
            return
        conn.execute(
            "INSERT INTO idempotency_records(operation,idempotency_key,request_sha256,response_json) VALUES(%s,%s,%s,%s::jsonb)",
            (operation, idempotency_key, request_sha256, canonical(response)),
        )

    def _resolve_dependency_sources(self, conn, sources: Sequence[dict[str, Any] | str]) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for source in sources:
            if isinstance(source, str):
                item_id = source
                content_sha256 = None
            else:
                item_id = str(source.get("item_id") or "")
                content_sha256 = str(source.get("content_sha256") or "") or None
            if not item_id:
                continue
            if content_sha256:
                row = conn.execute(
                    "SELECT v.version_id,v.version_no,v.content_sha256,m.tenant_id FROM memory_versions v JOIN memory_items m ON m.item_id=v.item_id WHERE v.item_id=%s AND v.content_sha256=%s ORDER BY v.version_no DESC LIMIT 1",
                    (item_id, content_sha256),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT v.version_id,v.version_no,v.content_sha256,m.tenant_id FROM memory_versions v JOIN memory_items m ON m.item_id=v.item_id WHERE v.item_id=%s ORDER BY v.version_no DESC LIMIT 1",
                    (item_id,),
                ).fetchone()
            if not row:
                raise KeyError(f"dependency source version not found: {item_id}")
            resolved.append({
                "item_id": item_id, "version_id": str(row["version_id"]),
                "version_no": int(row["version_no"]), "content_sha256": str(row["content_sha256"]),
                "tenant_id": str(row["tenant_id"]),
            })
        tenants = {x["tenant_id"] for x in resolved}
        if len(tenants) > 1:
            raise PermissionError("cross-tenant derived artifact dependencies are forbidden")
        return resolved

    def _register_derived_artifact_in_conn(
        self, conn, *, artifact_type: str, artifact_ref: str, artifact_sha256: str | None,
        sources: Sequence[dict[str, Any] | str], metadata: dict[str, Any] | None = None,
        status: str = "READY", invalidation_reason: str | None = None,
    ) -> dict[str, Any] | None:
        require_canonical_mutation("derived_artifact.register")
        resolved = self._resolve_dependency_sources(conn, sources)
        if not resolved:
            return None
        artifact_type = str(artifact_type).strip().upper()
        status = str(status).strip().upper()
        if status not in {"READY", "STALE", "INVALID"}:
            raise ValueError("invalid derived artifact status")
        tenant_id = resolved[0]["tenant_id"]
        material = {
            "artifact_type": artifact_type, "artifact_ref": str(artifact_ref),
            "artifact_sha256": artifact_sha256,
            "source_versions": sorted(x["version_id"] for x in resolved),
        }
        artifact_id = "art-" + sha256_json(material)[:40]
        source_version_ids = [str(source["version_id"]) for source in resolved]
        conn.execute(
            """SELECT memory_upsert_derived_artifact(
                 %s,%s,%s,%s,%s,%s::jsonb,%s,%s::text[]
               )""",
            (
                artifact_id,
                artifact_type,
                str(artifact_ref),
                artifact_sha256,
                status,
                canonical(metadata or {}),
                invalidation_reason,
                source_version_ids,
            ),
        )
        for source in resolved:
            dependency_id = "dep-" + sha256_json({"artifact_id":artifact_id,"version_id":source["version_id"],"kind":"DERIVED_FROM"})[:40]
            conn.execute(
                """INSERT INTO memory_artifact_dependencies(dependency_id,tenant_id,artifact_id,source_item_id,source_version_id,source_content_sha256,dependency_kind)
                   VALUES(%s,%s,%s,%s,%s,%s,'DERIVED_FROM') ON CONFLICT(artifact_id,source_version_id,dependency_kind) DO NOTHING""",
                (dependency_id,tenant_id,artifact_id,source["item_id"],source["version_id"],source["content_sha256"]),
            )
        self._audit(conn,"DERIVED_ARTIFACT_REGISTERED",artifact_id,{
            "artifact_type":artifact_type,"artifact_ref":str(artifact_ref),"status":status,
            "source_versions":[x["version_id"] for x in resolved],
        })
        return {"artifact_id":artifact_id,"artifact_type":artifact_type,"artifact_ref":str(artifact_ref),"status":status,"sources":resolved}

    def list_derived_artifacts(
        self, *, item_id: str | None = None, artifact_type: str | None = None,
        status: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses=["1=1"]
        params: list[Any]=[]
        if item_id:
            clauses.append("EXISTS(SELECT 1 FROM memory_artifact_dependencies d WHERE d.artifact_id=a.artifact_id AND d.source_item_id=%s)")
            params.append(item_id)
        if artifact_type:
            clauses.append("a.artifact_type=%s"); params.append(str(artifact_type).strip().upper())
        if status:
            clauses.append("a.status=%s"); params.append(str(status).strip().upper())
        params.append(min(max(int(limit),1),500))
        with self._connection() as conn:
            rows=conn.execute(
                # Dynamic SQL fragments below are fixed internal literals; caller values remain psycopg parameters.
                f"SELECT artifact_id,artifact_type,artifact_ref,artifact_sha256,status,metadata,invalidation_reason,stale_source_version_id,created_at,updated_at,staled_at,invalidated_at FROM memory_derived_artifacts a WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT %s",  # nosec B608
                tuple(params),
            ).fetchall()
        out=[]
        for row in rows:
            x=dict(row)
            for key in ("created_at","updated_at","staled_at","invalidated_at"):
                if x.get(key) is not None: x[key]=x[key].isoformat()
            out.append(x)
        return out

    def artifact_dependencies(self, artifact_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows=conn.execute(
                "SELECT dependency_id,artifact_id,source_item_id,source_version_id,source_content_sha256,dependency_kind,created_at FROM memory_artifact_dependencies WHERE artifact_id=%s ORDER BY created_at,source_item_id",
                (artifact_id,),
            ).fetchall()
        out=[]
        for row in rows:
            x=dict(row)
            if x.get("created_at") is not None: x["created_at"]=x["created_at"].isoformat()
            out.append(x)
        return out

    def remember(
        self,
        *,
        namespace: str,
        memory_key: str,
        content: dict[str, Any],
        content_text: str,
        provenance: dict[str, Any],
        confidence: float,
        source: str,
        category: str = "FACT",
        source_version: str | None = None,
        tags: list[str] | None = None,
        supersedes_id: str | None = None,
        changed_by: str = "system",
        idempotency_key: str | None = None,
        memory_scope: str = "GLOBAL_USER",
        memory_scope_ref: str | None = None,
        sharing_scope: str = "SYSTEM_SHARED",
        owner_user_id: str | None = None,
        owner_agent_id: str | None = None,
        project_id: str | None = None,
        team_id: str | None = None,
        organization_id: str | None = None,
        validation_status: str = "UNVALIDATED",
        governor_eligible: bool = False,
        occurred_at: datetime | None = None,
        observed_at: datetime | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> str:
        require_canonical_mutation('memory.remember')
        if not provenance:
            raise ValueError("provenance obrigatória")
        category = normalize_knowledge_type(category).value
        if category == "CAUSE":
            raise ValueError("direct CAUSE creation forbidden; create CORRELATION and use causal promotion")
        semantic_scope = self.access.validate_memory_scope(memory_scope, memory_scope_ref=memory_scope_ref)
        access_scope = self.access.validate_sharing_scope(
            sharing_scope,
            owner_user_id=owner_user_id,
            owner_agent_id=owner_agent_id,
            project_id=project_id,
            team_id=team_id,
            organization_id=organization_id,
        )
        request_temporal = idempotency_temporal_request(
            occurred_at=occurred_at, observed_at=observed_at, valid_from=valid_from, valid_to=valid_to
        )
        temporal = normalize_temporal_envelope(
            occurred_at=occurred_at, observed_at=observed_at, valid_from=valid_from, valid_to=valid_to
        )
        validation_status = str(validation_status or "UNVALIDATED").strip().upper()
        if validation_status not in {"UNVALIDATED", "VALIDATED", "REJECTED"}:
            raise ValueError("invalid validation_status")
        if governor_eligible:
            if access_scope["sharing_scope"] != "PROJECT_SHARED":
                raise PermissionError("governor_eligible memory must be PROJECT_SHARED")
            if not access_scope["project_id"]:
                raise PermissionError("governor_eligible memory requires project_id")
            if validation_status != "VALIDATED":
                raise PermissionError("governor_eligible memory must be VALIDATED")
        payload = {
            "namespace": namespace,
            "memory_key": memory_key,
            "content": content,
            "content_text": content_text,
            "provenance": provenance,
            "confidence": float(confidence),
            "source": source,
            "category": category,
            "source_version": source_version,
            "tags": tags or [],
            "supersedes_id": supersedes_id,
            "changed_by": changed_by,
            **semantic_scope,
            **access_scope,
            "temporal": request_temporal,
            "validation_status": validation_status,
            "governor_eligible": bool(governor_eligible),
        }
        request_hash = sha256_json(payload)
        content_hash = sha256_json(content)
        with self._connection() as conn:
            replay = self._idempotency_replay(
                conn, operation="remember", idempotency_key=idempotency_key, request_sha256=request_hash
            )
            if replay is not None:
                return str(replay["item_id"])
            item_id = f"mem-{uuid.uuid4().hex}"
            version_id = f"ver-{uuid.uuid4().hex}"
            event_id = f"evt-{uuid.uuid4().hex}"
            conn.execute(
                "INSERT INTO memory_items(item_id,namespace,memory_key,category,content_json,content_text,provenance,confidence,source,source_version,tags,supersedes_id,content_sha256,memory_scope,memory_scope_ref,sharing_scope,owner_user_id,owner_agent_id,project_id,team_id,organization_id,validation_status,governor_eligible,occurred_at,observed_at,valid_from,valid_to) VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (item_id, namespace, memory_key, category, canonical(content), content_text, canonical(provenance), float(confidence), source, source_version, tags or [], supersedes_id, content_hash, semantic_scope["memory_scope"], semantic_scope["memory_scope_ref"], access_scope["sharing_scope"], access_scope["owner_user_id"], access_scope["owner_agent_id"], access_scope["project_id"], access_scope["team_id"], access_scope["organization_id"], validation_status, bool(governor_eligible), temporal.occurred_at, temporal.observed_at, temporal.valid_from, temporal.valid_to),
            )
            conn.execute(
                "INSERT INTO memory_versions(version_id,item_id,version_no,content_json,content_text,provenance,confidence,source,source_version,tags,content_sha256,previous_version_id,request_sha256,created_by,occurred_at,observed_at,valid_from,valid_to) VALUES(%s,%s,1,%s::jsonb,%s,%s::jsonb,%s,%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s)",
                (version_id, item_id, canonical(content), content_text, canonical(provenance), float(confidence), source, source_version, tags or [], content_hash, request_hash, changed_by, temporal.occurred_at, temporal.observed_at, temporal.valid_from, temporal.valid_to),
            )
            conn.execute(
                "INSERT INTO memory_events(event_id,item_id,version_id,event_type,payload,request_sha256,occurred_at,observed_at,valid_from,valid_to) VALUES(%s,%s,%s,'MEMORY_CREATED',%s::jsonb,%s,%s,%s,%s,%s)",
                (event_id, item_id, version_id, canonical({"memory_key": memory_key, "content_sha256": content_hash, "memory_scope": semantic_scope["memory_scope"], "memory_scope_ref": semantic_scope["memory_scope_ref"]}), request_hash, temporal.occurred_at, temporal.observed_at, temporal.valid_from, temporal.valid_to),
            )
            conn.execute(
                "INSERT INTO memory_operator_state(item_id,operator_class,lifecycle_state,changed_by) VALUES(%s,'ATIVA','HOT',%s)",
                (item_id, changed_by),
            )
            self._audit(conn, "MEMORY_CREATED", item_id, {"memory_key": memory_key, "content_sha256": content_hash, "version_id": version_id, "memory_scope": semantic_scope["memory_scope"], "memory_scope_ref": semantic_scope["memory_scope_ref"], "temporal": temporal.as_dict()})
            self._idempotency_store(
                conn,
                operation="remember",
                idempotency_key=idempotency_key,
                request_sha256=request_hash,
                response={"item_id": item_id, "version_id": version_id, "version_no": 1},
            )
        return item_id

    def revise(
        self,
        item_id: str,
        *,
        content: dict[str, Any],
        content_text: str,
        provenance: dict[str, Any],
        confidence: float,
        source: str,
        source_version: str | None = None,
        tags: list[str] | None = None,
        changed_by: str = "system",
        idempotency_key: str | None = None,
        expected_version: int | None = None,
        occurred_at: datetime | None = None,
        observed_at: datetime | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> dict[str, Any]:
        require_canonical_mutation('memory.revise')
        if not provenance:
            raise ValueError("provenance obrigatória")
        request_temporal = idempotency_temporal_request(
            occurred_at=occurred_at, observed_at=observed_at, valid_from=valid_from, valid_to=valid_to
        )
        temporal = normalize_temporal_envelope(
            occurred_at=occurred_at, observed_at=observed_at, valid_from=valid_from, valid_to=valid_to
        )
        payload = {
            "item_id": item_id,
            "content": content,
            "content_text": content_text,
            "provenance": provenance,
            "confidence": float(confidence),
            "source": source,
            "source_version": source_version,
            "tags": tags or [],
            "changed_by": changed_by,
            "expected_version": expected_version,
            "temporal": request_temporal,
        }
        request_hash = sha256_json(payload)
        content_hash = sha256_json(content)
        operation = f"revise:{item_id}"
        with self._connection() as conn:
            replay = self._idempotency_replay(
                conn, operation=operation, idempotency_key=idempotency_key, request_sha256=request_hash
            )
            if replay is not None:
                return replay
            current = conn.execute(
                "SELECT item_id,validation_status,governor_eligible,content_sha256 FROM memory_items WHERE item_id=%s FOR UPDATE", (item_id,)
            ).fetchone()
            if not current:
                raise KeyError(item_id)
            previous = conn.execute(
                "SELECT version_id,version_no FROM memory_versions WHERE item_id=%s ORDER BY version_no DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            current_version = int(previous["version_no"] if previous else 0)
            if expected_version is not None and current_version != int(expected_version):
                raise ConcurrencyConflict(
                    f"expected_version={expected_version} current_version={current_version} item_id={item_id}"
                )
            previous_id = str(previous["version_id"]) if previous else None
            version_no = current_version + 1
            version_id = f"ver-{uuid.uuid4().hex}"
            event_id = f"evt-{uuid.uuid4().hex}"
            previous_validation = str(current.get("validation_status") or "UNVALIDATED")
            previous_governor_eligible = bool(current.get("governor_eligible"))
            conn.execute(
                "UPDATE memory_items SET content_json=%s::jsonb,content_text=%s,provenance=%s::jsonb,confidence=%s,source=%s,source_version=%s,tags=%s,content_sha256=%s,occurred_at=%s,observed_at=%s,valid_from=%s,valid_to=%s,validation_status='UNVALIDATED',governor_eligible=false WHERE item_id=%s",
                (canonical(content), content_text, canonical(provenance), float(confidence), source, source_version, tags or [], content_hash, temporal.occurred_at, temporal.observed_at, temporal.valid_from, temporal.valid_to, item_id),
            )
            conn.execute("UPDATE memory_embeddings SET status='STALE',updated_at=now() WHERE item_id=%s", (item_id,))
            conn.execute(
                "INSERT INTO memory_versions(version_id,item_id,version_no,content_json,content_text,provenance,confidence,source,source_version,tags,content_sha256,previous_version_id,request_sha256,created_by,occurred_at,observed_at,valid_from,valid_to) VALUES(%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (version_id, item_id, version_no, canonical(content), content_text, canonical(provenance), float(confidence), source, source_version, tags or [], content_hash, previous_id, request_hash, changed_by, temporal.occurred_at, temporal.observed_at, temporal.valid_from, temporal.valid_to),
            )
            conn.execute(
                "INSERT INTO memory_events(event_id,item_id,version_id,event_type,payload,request_sha256,occurred_at,observed_at,valid_from,valid_to) VALUES(%s,%s,%s,'MEMORY_REVISED',%s::jsonb,%s,%s,%s,%s,%s)",
                (event_id, item_id, version_id, canonical({"version_no": version_no, "content_sha256": content_hash, "previous_version_id": previous_id}), request_hash, temporal.occurred_at, temporal.observed_at, temporal.valid_from, temporal.valid_to),
            )
            self._audit(conn, "MEMORY_REVISED", item_id, {"version_id": version_id, "version_no": version_no, "content_sha256": content_hash, "temporal": temporal.as_dict()})
            if previous_id:
                invalidated=conn.execute("SELECT count(*) AS n,array_agg(DISTINCT artifact_type) AS types FROM memory_derived_artifacts WHERE stale_source_version_id=%s AND status='STALE'",(previous_id,)).fetchone()
                if invalidated and int(invalidated["n"] or 0)>0:
                    self._audit(conn,"DERIVED_ARTIFACTS_INVALIDATED",item_id,{
                        "source_version_id":previous_id,"new_version_id":version_id,
                        "artifact_count":int(invalidated["n"]),"artifact_types":list(invalidated.get("types") or []),
                        "reason":"SOURCE_VERSION_SUPERSEDED",
                    })
            if previous_validation != "UNVALIDATED" or previous_governor_eligible:
                self._audit(conn, "MEMORY_VALIDATION_INVALIDATED", item_id, {
                    "previous_validation_status": previous_validation,
                    "previous_governor_eligible": previous_governor_eligible,
                    "new_validation_status": "UNVALIDATED",
                    "new_governor_eligible": False,
                    "reason": "CONTENT_CHANGED",
                    "version_id": version_id,
                    "version_no": version_no,
                    "content_sha256": content_hash,
                })
            response = {"item_id": item_id, "version_id": version_id, "version_no": version_no, "status": "REVISED", "validation_status": "UNVALIDATED", "governor_eligible": False, "temporal": temporal.as_dict()}
            self._idempotency_store(
                conn,
                operation=operation,
                idempotency_key=idempotency_key,
                request_sha256=request_hash,
                response=response,
            )
            return response

    def validate_current_version(
        self, item_id: str, *, expected_version: int, expected_content_sha256: str, status: str,
        governor_eligible: bool, validator_client_id: str, evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        require_canonical_mutation('memory.validate')
        status = str(status).strip().upper()
        if status not in {"VALIDATED", "REJECTED"}:
            raise ValueError("validation status must be VALIDATED or REJECTED")
        if status != "VALIDATED" and governor_eligible:
            raise PermissionError("only VALIDATED memory can be governor_eligible")
        with self._connection() as conn:
            item = conn.execute(
                "SELECT item_id,sharing_scope,project_id,content_sha256 FROM memory_items WHERE item_id=%s FOR UPDATE",
                (item_id,),
            ).fetchone()
            if not item:
                raise KeyError(item_id)
            version = conn.execute(
                "SELECT version_id,version_no,content_sha256 FROM memory_versions WHERE item_id=%s ORDER BY version_no DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            if not version:
                raise KeyError(item_id)
            if int(version["version_no"]) != int(expected_version):
                raise ConcurrencyConflict(f"validation expected_version={expected_version} current_version={version['version_no']}")
            if str(version["content_sha256"]) != str(expected_content_sha256) or str(item["content_sha256"]) != str(expected_content_sha256):
                raise ConcurrencyConflict("validation content hash mismatch")
            if governor_eligible and (str(item["sharing_scope"]) != "PROJECT_SHARED" or not item.get("project_id")):
                raise PermissionError("governor_eligible memory requires PROJECT_SHARED project memory")
            validation_id = f"val-{uuid.uuid4().hex}"
            conn.execute(
                "INSERT INTO memory_validations(validation_id,item_id,version_id,version_no,content_sha256,status,governor_eligible,validator_client_id,evidence) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (validation_id,item_id,version["version_id"],version["version_no"],version["content_sha256"],status,bool(governor_eligible),validator_client_id,canonical(evidence or {})),
            )
            conn.execute(
                "UPDATE memory_items SET validation_status=%s,governor_eligible=%s WHERE item_id=%s",
                (status, bool(governor_eligible and status == "VALIDATED"), item_id),
            )
            self._audit(conn, "MEMORY_VALIDATED" if status == "VALIDATED" else "MEMORY_REJECTED", item_id, {
                "validation_id": validation_id, "version_id": version["version_id"], "version_no": int(version["version_no"]),
                "content_sha256": version["content_sha256"], "governor_eligible": bool(governor_eligible and status == "VALIDATED"),
                "validator_client_id": validator_client_id,
            })
        return {"validation_id":validation_id,"item_id":item_id,"version_id":str(version["version_id"]),"version_no":int(version["version_no"]),"content_sha256":str(version["content_sha256"]),"validation_status":status,"governor_eligible":bool(governor_eligible and status == "VALIDATED")}

    def record_application(
        self, item_id: str, *, action_ref: str, applied_by_client_id: str, mission_id: str | None = None,
        decision_id: str | None = None, context: dict[str, Any] | None = None, occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        require_canonical_mutation('experience.application')
        occurred = occurred_at or datetime.now(UTC)
        with self._connection() as conn:
            item = conn.execute("SELECT item_id,content_sha256 FROM memory_items WHERE item_id=%s FOR UPDATE", (item_id,)).fetchone()
            if not item:
                raise KeyError(item_id)
            version = conn.execute(
                "SELECT version_id,version_no,content_sha256,confidence FROM memory_versions WHERE item_id=%s ORDER BY version_no DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            if not version:
                raise KeyError(item_id)
            if decision_id:
                formal = conn.execute("SELECT mission_id FROM sovereign_decisions WHERE decision_id=%s",(decision_id,)).fetchone()
                if not formal:
                    raise ValueError("decision_id must reference a formal sovereign decision")
                if not mission_id or str(mission_id) != str(formal["mission_id"]):
                    raise ValueError("application mission_id must match formal sovereign decision mission")
            if decision_id:
                decision=conn.execute("SELECT tenant_id,mission_id FROM sovereign_decisions WHERE decision_id=%s",(decision_id,)).fetchone()
                if not decision:
                    raise ValueError("decision_id must reference a formal sovereign decision")
                if not mission_id or str(mission_id) != str(decision["mission_id"]):
                    raise ValueError("application mission_id must match formal decision mission")
                if str(decision["tenant_id"]) != str(self.tenant_id):
                    raise PermissionError("application decision is outside current tenant")
            application_id = f"app-{uuid.uuid4().hex}"
            conn.execute(
                "INSERT INTO memory_applications(application_id,item_id,version_id,content_sha256,mission_id,decision_id,action_ref,context,applied_by_client_id,occurred_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)",
                (application_id,item_id,version['version_id'],version['content_sha256'],mission_id,decision_id,action_ref,canonical(context or {}),applied_by_client_id,occurred),
            )
            conn.execute(
                """INSERT INTO memory_version_learning(version_id,item_id,version_no,content_sha256,base_confidence,learned_confidence,application_count,current_policy_version)
                VALUES(%s,%s,%s,%s,%s,%s,1,%s)
                ON CONFLICT(version_id) DO UPDATE SET application_count=memory_version_learning.application_count+1,updated_at=now()""",
                (version['version_id'],item_id,int(version['version_no']),version['content_sha256'],float(version['confidence']),float(version['confidence']),POLICY_VERSION),
            )
            conn.execute("UPDATE memory_items SET application_count=application_count+1,last_used_at=now() WHERE item_id=%s", (item_id,))
            if decision_id:
                conn.execute("INSERT INTO memory_experience_edges(edge_id,from_type,from_id,relation,to_type,to_id,evidence,occurred_at) VALUES(%s,'DECISION',%s,'USED','MEMORY',%s,%s::jsonb,%s)", (f"edge-{uuid.uuid4().hex}",decision_id,item_id,canonical({'application_id':application_id,'version_id':version['version_id']}),occurred))
            self._audit(conn,"MEMORY_APPLIED",item_id,{"application_id":application_id,"version_id":version['version_id'],"version_no":int(version['version_no']),"content_sha256":version['content_sha256'],"action_ref":action_ref,"decision_id":decision_id,"mission_id":mission_id,"applied_by_client_id":applied_by_client_id})
        return {"application_id":application_id,"item_id":item_id,"version_id":str(version['version_id']),"version_no":int(version['version_no']),"content_sha256":str(version['content_sha256']),"occurred_at":occurred.isoformat()}

    def record_outcome(
        self, application_id: str, *, success: bool, outcome_type: str, expected: dict[str, Any] | None,
        actual: dict[str, Any] | None, evidence: dict[str, Any] | None = None, occurred_at: datetime | None = None,
        authority_tier: str = "AUTHENTICATED", caller_confidence_delta_present: bool = False,
    ) -> dict[str, Any]:
        require_canonical_mutation('experience.outcome')
        occurred = occurred_at or datetime.now(UTC)
        observed = datetime.now(UTC)
        engine = LearningPolicyEngine()
        with self._connection() as conn:
            application = conn.execute(
                "SELECT application_id,item_id,version_id,content_sha256 FROM memory_applications WHERE application_id=%s FOR UPDATE",
                (application_id,),
            ).fetchone()
            if not application:
                raise KeyError(application_id)
            item_id = str(application['item_id'])
            item = conn.execute("SELECT item_id,confidence FROM memory_items WHERE item_id=%s FOR UPDATE", (item_id,)).fetchone()
            if not item:
                raise KeyError(item_id)
            version = conn.execute(
                "SELECT version_id,version_no,content_sha256,confidence FROM memory_versions WHERE version_id=%s AND item_id=%s",
                (application['version_id'],item_id),
            ).fetchone()
            if not version or str(version['content_sha256']) != str(application['content_sha256']):
                raise ConcurrencyConflict('application version/hash no longer resolves exactly')
            current_version = conn.execute(
                "SELECT version_id,version_no,content_sha256 FROM memory_versions WHERE item_id=%s ORDER BY version_no DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            projection = conn.execute(
                "SELECT * FROM memory_version_learning WHERE version_id=%s FOR UPDATE",
                (version['version_id'],),
            ).fetchone()
            if not projection:
                conn.execute(
                    "INSERT INTO memory_version_learning(version_id,item_id,version_no,content_sha256,base_confidence,learned_confidence,application_count,current_policy_version) VALUES(%s,%s,%s,%s,%s,%s,1,%s)",
                    (version['version_id'],item_id,int(version['version_no']),version['content_sha256'],float(version['confidence']),float(version['confidence']),POLICY_VERSION),
                )
                projection = conn.execute("SELECT * FROM memory_version_learning WHERE version_id=%s FOR UPDATE", (version['version_id'],)).fetchone()
            prior_successes = int(projection['success_count'] or 0)
            prior_failures = int(projection['failure_count'] or 0)
            decision = engine.evaluate(
                success=bool(success), expected=expected or {}, actual=actual or {}, evidence=evidence or {},
                authority_tier=authority_tier, prior_successes=prior_successes, prior_failures=prior_failures,
                occurred_at=occurred, observed_at=observed,
            )
            confidence_before = float(projection['learned_confidence'])
            confidence_after = max(0.0,min(1.0,confidence_before + decision.computed_delta))
            current_match = bool(current_version and str(current_version['version_id']) == str(version['version_id']))
            outcome_id = f"out-{uuid.uuid4().hex}"
            learning_event_id = f"learn-{uuid.uuid4().hex}"
            conn.execute(
                """INSERT INTO memory_outcomes(outcome_id,application_id,item_id,success,outcome_type,expected,actual,confidence_delta,evidence,occurred_at,policy_version,computed_confidence_delta,learning_event_id)
                VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s,%s,%s,%s)""",
                (outcome_id,application_id,item_id,bool(success),str(outcome_type),canonical(expected or {}),canonical(actual or {}),decision.computed_delta,canonical(evidence or {}),occurred,decision.policy_version,decision.computed_delta,learning_event_id),
            )
            conn.execute(
                """INSERT INTO memory_learning_events(learning_event_id,outcome_id,application_id,item_id,version_id,version_no,content_sha256,policy_version,success,authority_tier,components,computed_delta,confidence_before,confidence_after,applied_to_current_item,occurred_at,observed_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s)""",
                (learning_event_id,outcome_id,application_id,item_id,version['version_id'],int(version['version_no']),version['content_sha256'],decision.policy_version,bool(success),str(authority_tier).upper(),canonical(decision.components),decision.computed_delta,confidence_before,confidence_after,current_match,occurred,observed),
            )
            conn.execute(
                """UPDATE memory_version_learning SET success_count=success_count+%s,failure_count=failure_count+%s,evidence_weight=evidence_weight+%s,learned_confidence=%s,current_policy_version=%s,last_outcome_at=%s,updated_at=now() WHERE version_id=%s""",
                (1 if success else 0,0 if success else 1,float(decision.components['evidence_weight']),confidence_after,decision.policy_version,observed,version['version_id']),
            )
            if current_match:
                conn.execute(
                    "UPDATE memory_items SET success_count=success_count+%s,failure_count=failure_count+%s,confidence=%s WHERE item_id=%s",
                    (1 if success else 0,0 if success else 1,confidence_after,item_id),
                )
            else:
                conn.execute(
                    "UPDATE memory_items SET success_count=success_count+%s,failure_count=failure_count+%s WHERE item_id=%s",
                    (1 if success else 0,0 if success else 1,item_id),
                )
            conn.execute("INSERT INTO memory_experience_edges(edge_id,from_type,from_id,relation,to_type,to_id,evidence,occurred_at) VALUES(%s,'APPLICATION',%s,'PRODUCED','OUTCOME',%s,%s::jsonb,%s)", (f"edge-{uuid.uuid4().hex}",application_id,outcome_id,canonical({'success':bool(success),'version_id':version['version_id']}),occurred))
            relation = "CONFIRMED" if success else "CONTRADICTED"
            conn.execute("INSERT INTO memory_experience_edges(edge_id,from_type,from_id,relation,to_type,to_id,evidence,occurred_at) VALUES(%s,'OUTCOME',%s,%s,'MEMORY',%s,%s::jsonb,%s)", (f"edge-{uuid.uuid4().hex}",outcome_id,relation,item_id,canonical({'computed_delta':decision.computed_delta,'policy_version':decision.policy_version,'version_id':version['version_id']}),occurred))
            if decision.computed_delta != 0:
                relation2 = "INCREASED_CONFIDENCE" if decision.computed_delta > 0 else "DECREASED_CONFIDENCE"
                conn.execute("INSERT INTO memory_experience_edges(edge_id,from_type,from_id,relation,to_type,to_id,evidence,occurred_at) VALUES(%s,'OUTCOME',%s,%s,'MEMORY',%s,%s::jsonb,%s)", (f"edge-{uuid.uuid4().hex}",outcome_id,relation2,item_id,canonical({'computed_delta':decision.computed_delta,'policy_version':decision.policy_version,'version_id':version['version_id']}),occurred))
            self._audit(conn,"MEMORY_OUTCOME_RECORDED",item_id,{
                "application_id":application_id,"outcome_id":outcome_id,"learning_event_id":learning_event_id,
                "version_id":version['version_id'],"version_no":int(version['version_no']),"content_sha256":version['content_sha256'],
                "success":bool(success),"outcome_type":str(outcome_type),"policy_version":decision.policy_version,
                "computed_confidence_delta":decision.computed_delta,"applied_to_current_item":current_match,
                "caller_confidence_delta_ignored":bool(caller_confidence_delta_present),
            })
            counters = conn.execute("SELECT application_count,success_count,failure_count,confidence FROM memory_items WHERE item_id=%s", (item_id,)).fetchone()
        return {
            "outcome_id":outcome_id,"learning_event_id":learning_event_id,"application_id":application_id,"item_id":item_id,
            "version_id":str(version['version_id']),"version_no":int(version['version_no']),"success":bool(success),
            "policy_version":decision.policy_version,"computed_confidence_delta":decision.computed_delta,
            "version_confidence_before":confidence_before,"version_confidence_after":confidence_after,
            "applied_to_current_item":current_match,"caller_confidence_delta_ignored":bool(caller_confidence_delta_present),
            "application_count":int(counters['application_count']),"success_count":int(counters['success_count']),
            "failure_count":int(counters['failure_count']),"confidence":float(counters['confidence']),"occurred_at":occurred.isoformat(),
        }

    def version_learning(self, item_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT version_id,item_id,version_no,content_sha256,base_confidence,learned_confidence,application_count,success_count,failure_count,evidence_weight,current_policy_version,last_outcome_at,updated_at FROM memory_version_learning WHERE item_id=%s ORDER BY version_no",
                (item_id,),
            ).fetchall()
        result=[]
        for row in rows:
            value=dict(row)
            for key in ('last_outcome_at','updated_at'):
                if value.get(key) is not None:
                    value[key]=value[key].isoformat()
            result.append(value)
        return result

    def create_experience_graph_node(
        self, *, mission_id: str, node_type: str, entity_ref: str, payload: dict[str, Any], provenance: dict[str, Any],
        created_by: str, occurred_at: datetime | None = None, memory_item_id: str | None = None,
        memory_version_id: str | None = None,
    ) -> dict[str, Any]:
        require_canonical_mutation('experience.graph.node')
        mission = str(mission_id or '').strip()
        ref = str(entity_ref or '').strip()
        if not mission or len(mission) > 240:
            raise ValueError('invalid mission_id')
        if not ref or len(ref) > 300:
            raise ValueError('invalid entity_ref')
        kind = normalize_node_type(node_type)
        occurred = occurred_at or datetime.now(UTC)
        with self._connection() as conn:
            bound_item = None
            bound_version = None
            bound_hash = None
            bound_category = None
            if memory_version_id and not memory_item_id:
                raise ValueError('memory_version_id requires memory_item_id')
            if memory_item_id:
                bound_item = conn.execute(
                    'SELECT item_id,tenant_id,category FROM memory_items WHERE item_id=%s', (memory_item_id,)
                ).fetchone()
                if not bound_item:
                    raise KeyError(memory_item_id)
                if str(bound_item['tenant_id']) != self.tenant_id:
                    raise PermissionError('experience graph memory binding tenant mismatch')
                if memory_version_id:
                    bound_version = conn.execute(
                        'SELECT version_id,item_id,content_sha256 FROM memory_versions WHERE version_id=%s AND item_id=%s',
                        (memory_version_id,memory_item_id),
                    ).fetchone()
                else:
                    bound_version = conn.execute(
                        'SELECT version_id,item_id,content_sha256 FROM memory_versions WHERE item_id=%s ORDER BY version_no DESC LIMIT 1',
                        (memory_item_id,),
                    ).fetchone()
                if not bound_version:
                    raise ValueError('experience graph requires an exact memory version')
                bound_hash = str(bound_version['content_sha256'])
                bound_category = str(bound_item['category'])
                validate_memory_binding(kind,bound_category)
            node_id=f'egn-{uuid.uuid4().hex}'
            conn.execute(
                '''INSERT INTO experience_graph_nodes(
                    node_id,tenant_id,mission_id,node_type,entity_ref,memory_item_id,memory_version_id,memory_content_sha256,memory_category_snapshot,
                    payload,provenance,occurred_at,created_by
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)''',
                (node_id,self.tenant_id,mission,kind.value,ref,memory_item_id,
                 str(bound_version['version_id']) if bound_version else None,bound_hash,bound_category,
                 canonical(payload or {}),canonical(provenance or {}),occurred,created_by),
            )
            self._audit(conn,'EXPERIENCE_GRAPH_NODE_CREATED',node_id,{
                'mission_id':mission,'node_type':kind.value,'entity_ref':ref,'memory_item_id':memory_item_id,
                'memory_version_id':str(bound_version['version_id']) if bound_version else None,
            })
        return {
            'node_id':node_id,'mission_id':mission,'node_type':kind.value,'entity_ref':ref,
            'memory_item_id':memory_item_id,'memory_version_id':str(bound_version['version_id']) if bound_version else None,
            'memory_content_sha256':bound_hash,'memory_category_snapshot':bound_category,'occurred_at':occurred.isoformat(),
        }

    def create_experience_graph_edge(
        self, *, mission_id: str, from_node_id: str, relation_type: str, to_node_id: str, evidence: dict[str, Any],
        created_by: str, occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        require_canonical_mutation('experience.graph.edge')
        mission=str(mission_id or '').strip()
        if not mission or len(mission)>240:
            raise ValueError('invalid mission_id')
        occurred=occurred_at or datetime.now(UTC)
        with self._connection() as conn:
            source=conn.execute(
                'SELECT node_id,mission_id,node_type,occurred_at FROM experience_graph_nodes WHERE node_id=%s', (from_node_id,)
            ).fetchone()
            target=conn.execute(
                'SELECT node_id,mission_id,node_type,occurred_at FROM experience_graph_nodes WHERE node_id=%s', (to_node_id,)
            ).fetchone()
            if not source:
                raise KeyError(from_node_id)
            if not target:
                raise KeyError(to_node_id)
            if str(source['mission_id'])!=mission or str(target['mission_id'])!=mission:
                raise PermissionError('cross-mission experience graph edge forbidden')
            _,rel,_=validate_edge_rule(str(source['node_type']),relation_type,str(target['node_type']))
            if target['occurred_at'] < source['occurred_at']:
                raise ValueError('experience graph causal target occurs before source')
            if occurred < target['occurred_at']:
                raise ValueError('experience graph edge occurs before target entity')
            graph_edge_id=f'ege-{uuid.uuid4().hex}'
            conn.execute(
                'INSERT INTO experience_graph_edges(graph_edge_id,tenant_id,mission_id,from_node_id,relation_type,to_node_id,evidence,occurred_at,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)',
                (graph_edge_id,self.tenant_id,mission,from_node_id,rel.value,to_node_id,canonical(evidence or {}),occurred,created_by),
            )
            self._audit(conn,'EXPERIENCE_GRAPH_EDGE_CREATED',graph_edge_id,{
                'mission_id':mission,'from_node_id':from_node_id,'relation_type':rel.value,'to_node_id':to_node_id,
            })
        return {'graph_edge_id':graph_edge_id,'mission_id':mission,'from_node_id':from_node_id,'relation_type':rel.value,'to_node_id':to_node_id,'occurred_at':occurred.isoformat()}

    def mission_experience_graph(self, mission_id: str) -> dict[str, Any]:
        mission=str(mission_id or '').strip()
        if not mission:
            raise ValueError('invalid mission_id')
        with self._connection() as conn:
            node_rows=conn.execute(
                '''SELECT node_id,mission_id,node_type,entity_ref,memory_item_id,memory_version_id,memory_content_sha256,memory_category_snapshot,
                          payload,provenance,occurred_at,observed_at,created_by,created_at
                   FROM experience_graph_nodes WHERE mission_id=%s ORDER BY occurred_at,node_id''', (mission,)
            ).fetchall()
            edge_rows=conn.execute(
                '''SELECT graph_edge_id,mission_id,from_node_id,relation_type AS relation,to_node_id,evidence,occurred_at,observed_at,created_by,created_at
                   FROM experience_graph_edges WHERE mission_id=%s ORDER BY occurred_at,graph_edge_id''', (mission,)
            ).fetchall()
        nodes=[]
        for row in node_rows:
            x=dict(row)
            for key in ('occurred_at','observed_at','created_at'):
                if x.get(key) is not None: x[key]=x[key].isoformat()
            nodes.append(x)
        edges=[]
        for row in edge_rows:
            x=dict(row)
            for key in ('occurred_at','observed_at','created_at'):
                if x.get(key) is not None: x[key]=x[key].isoformat()
            edges.append(x)
        reconstruction=reconstruct_mission_graph(nodes,edges)
        return {'mission_id':mission,'nodes':nodes,'edges':edges,'reconstruction':reconstruction}

    def experience_graph(self, *, node_type: str, node_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows=conn.execute("SELECT edge_id,from_type,from_id,relation,to_type,to_id,evidence,occurred_at,observed_at FROM memory_experience_edges WHERE (from_type=%s AND from_id=%s) OR (to_type=%s AND to_id=%s) ORDER BY observed_at DESC LIMIT %s",(node_type,node_id,node_type,node_id,min(max(int(limit),1),500))).fetchall()
        result=[]
        for row in rows:
            x=dict(row)
            for k in ("occurred_at","observed_at"):
                if x.get(k) is not None: x[k]=x[k].isoformat()
            result.append(x)
        return result

    def list_versions(self, item_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn:
            visible = conn.execute("SELECT 1 FROM memory_items WHERE item_id=%s", (item_id,)).fetchone()
            if not visible:
                return []
            rows = conn.execute(
                "SELECT version_id,item_id,version_no,content_json,content_text,provenance,confidence,source,source_version,tags,content_sha256,previous_version_id,request_sha256,created_by,occurred_at,observed_at,valid_from,valid_to,created_at FROM memory_versions WHERE item_id=%s ORDER BY version_no",
                (item_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            value = dict(row)
            for key in ("occurred_at", "observed_at", "valid_from", "valid_to", "created_at"):
                if value.get(key) is not None:
                    value[key] = value[key].isoformat()
            result.append(value)
        return result

    def classify(self, item_ids: list[str], operator_class: str, *, changed_by: str) -> dict[str, Any]:
        require_canonical_mutation('memory.classify')
        decision = map_operator_class(operator_class)
        updated = 0
        with self._connection() as conn:
            for item_id in item_ids:
                exists = conn.execute("SELECT 1 FROM memory_items WHERE item_id=%s", (item_id,)).fetchone()
                if not exists:
                    continue
                conn.execute(
                    "INSERT INTO memory_operator_state(item_id,operator_class,lifecycle_state,hold_type,changed_by,changed_at) VALUES(%s,%s,%s,%s,%s,now()) ON CONFLICT(item_id) DO UPDATE SET operator_class=EXCLUDED.operator_class,lifecycle_state=EXCLUDED.lifecycle_state,hold_type=EXCLUDED.hold_type,changed_by=EXCLUDED.changed_by,changed_at=now()",
                    (item_id, decision.operator_class.value, decision.lifecycle_state.value, decision.hold_type.value if decision.hold_type else None, changed_by),
                )
                if decision.hold_type is not None:
                    active = conn.execute("SELECT 1 FROM retention_holds WHERE item_id=%s AND status='ACTIVE' AND hold_type=%s", (item_id, decision.hold_type.value)).fetchone()
                    if not active:
                        conn.execute(
                            "INSERT INTO retention_holds(hold_id,item_id,hold_type,reason,created_by) VALUES(%s,%s,%s,%s,%s)",
                            (f"hold-{uuid.uuid4().hex}", item_id, decision.hold_type.value, f"operator_class:{decision.operator_class.value}", changed_by),
                        )
                self._audit(conn, "MEMORY_CLASSIFIED", item_id, {"operator_class": decision.operator_class.value, "lifecycle_state": decision.lifecycle_state.value, "hold_type": decision.hold_type.value if decision.hold_type else None, "purge_allowed": False, "changed_by": changed_by})
                updated += 1
        return {"updated": updated, "operator_class": decision.operator_class.value, "lifecycle_state": decision.lifecycle_state.value, "purge_allowed": False}

    def create_knowledge_relation(
        self, *, from_item_id: str, relation_type: str, to_item_id: str, provenance: dict[str, Any],
        confidence: float, created_by: str,
    ) -> dict[str, Any]:
        require_canonical_mutation('ontology.relation')
        if from_item_id == to_item_id:
            raise ValueError("knowledge relation cannot target itself")
        with self._connection() as conn:
            source = conn.execute("SELECT item_id,category,tenant_id FROM memory_items WHERE item_id=%s",(from_item_id,)).fetchone()
            target = conn.execute("SELECT item_id,category,tenant_id FROM memory_items WHERE item_id=%s",(to_item_id,)).fetchone()
            if not source:
                raise KeyError(from_item_id)
            if not target:
                raise KeyError(to_item_id)
            if str(source['tenant_id']) != str(target['tenant_id']):
                raise PermissionError("cross-tenant knowledge relation forbidden")
            _, rel, _ = validate_relation(str(source['category']),relation_type,str(target['category']))
            source_v=conn.execute("SELECT version_id FROM memory_versions WHERE item_id=%s ORDER BY version_no DESC LIMIT 1",(from_item_id,)).fetchone()
            target_v=conn.execute("SELECT version_id FROM memory_versions WHERE item_id=%s ORDER BY version_no DESC LIMIT 1",(to_item_id,)).fetchone()
            if not source_v or not target_v:
                raise ValueError("knowledge relation requires versioned memories")
            relation_id=f"rel-{uuid.uuid4().hex}"
            conn.execute("""INSERT INTO memory_knowledge_relations(relation_id,tenant_id,from_item_id,from_version_id,relation_type,to_item_id,to_version_id,provenance,confidence,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",
                (relation_id,self.tenant_id,from_item_id,source_v['version_id'],rel.value,to_item_id,target_v['version_id'],canonical(provenance or {}),float(confidence),created_by))
            self._audit(conn,"KNOWLEDGE_RELATION_CREATED",relation_id,{"from_item_id":from_item_id,"from_version_id":str(source_v['version_id']),"relation_type":rel.value,"to_item_id":to_item_id,"to_version_id":str(target_v['version_id'])})
            return {"relation_id":relation_id,"from_item_id":from_item_id,"from_version_id":str(source_v['version_id']),"relation_type":rel.value,"to_item_id":to_item_id,"to_version_id":str(target_v['version_id']),"status":"ACTIVE"}

    def list_knowledge_relations(self, item_id: str, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any]=[item_id,item_id]
        clause="(r.from_item_id=%s OR r.to_item_id=%s)"
        if status:
            normalized=str(status).strip().upper()
            if normalized not in {"ACTIVE","STALE"}:
                raise ValueError("invalid knowledge relation status")
            clause += " AND r.status=%s"
            params.append(normalized)
        params.append(min(max(int(limit),1),500))
        relation_query = pg_sql.SQL("""SELECT r.relation_id,r.from_item_id,r.from_version_id,r.from_category,r.relation_type,r.to_item_id,r.to_version_id,r.to_category,r.provenance,r.confidence,r.status,r.created_by,r.created_at,r.staled_at,r.stale_reason
                FROM memory_knowledge_relations r
                WHERE {} ORDER BY r.created_at DESC LIMIT %s""").format(pg_sql.SQL(clause))
        with self._connection() as conn:
            rows=conn.execute(relation_query,tuple(params)).fetchall()
        out=[]
        for row in rows:
            x=dict(row)
            for k in ("created_at","staled_at"):
                if x.get(k) is not None:
                    x[k]=x[k].isoformat()
            out.append(x)
        return out

    def transition_knowledge_type(self, *, item_id: str, to_category: str, reason: str, evidence: dict[str, Any], actor_id_value: str) -> dict[str, Any]:
        require_canonical_mutation('ontology.transition')
        if not str(reason or '').strip():
            raise ValueError("ontology transition reason is required")
        with self._connection() as conn:
            item=conn.execute("SELECT category,validation_status,governor_eligible FROM memory_items WHERE item_id=%s FOR UPDATE",(item_id,)).fetchone()
            if not item:
                raise KeyError(item_id)
            src,dst=validate_transition(str(item['category']),to_category)
            if dst.value == "CAUSE":
                raise ValueError("generic ontology transition cannot promote CAUSE; use causal promotion")
            transition_id=f"trn-{uuid.uuid4().hex}"
            conn.execute("SELECT memory_apply_ontology_transition(%s,%s,%s,%s,%s,%s::jsonb)",(transition_id,item_id,dst.value,actor_id_value,str(reason).strip(),canonical(evidence or {})))
            self._audit(conn,"MEMORY_ONTOLOGY_TRANSITION",item_id,{"transition_id":transition_id,"from_category":src.value,"to_category":dst.value,"reason":str(reason).strip(),"previous_validation_status":str(item.get('validation_status') or 'UNVALIDATED'),"previous_governor_eligible":bool(item.get('governor_eligible'))})
            return {"transition_id":transition_id,"item_id":item_id,"from_category":src.value,"to_category":dst.value,"validation_status":"UNVALIDATED","governor_eligible":False}

    def create_causal_assessment(
        self, item_id: str, *, hypothesis: dict[str, Any], intervention: dict[str, Any], comparator: dict[str, Any],
        confounders: list[Any], confounder_control: dict[str, Any], mechanism: dict[str, Any], counterfactual: dict[str, Any],
        attribution_confidence: float, sample_size: int, repetition_count: int, evidence: dict[str, Any],
        created_by: str, occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        require_canonical_mutation('causal.assessment')
        occurred = occurred_at or datetime.now(UTC)
        with self._connection() as conn:
            item = conn.execute(
                "SELECT item_id,tenant_id,category,content_sha256 FROM memory_items WHERE item_id=%s FOR UPDATE",
                (item_id,),
            ).fetchone()
            if not item:
                raise KeyError(item_id)
            if str(item['category']) != 'CORRELATION':
                raise ValueError('causal assessment requires current CORRELATION memory')
            version = conn.execute(
                "SELECT version_id,version_no,content_sha256 FROM memory_versions WHERE item_id=%s ORDER BY version_no DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            if not version or str(version['content_sha256']) != str(item['content_sha256']):
                raise ConcurrencyConflict('current memory version/hash does not resolve exactly')
            decision = evaluate_causal_assessment(
                source_category=str(item['category']), hypothesis=hypothesis, intervention=intervention,
                comparator=comparator, confounders=confounders, confounder_control=confounder_control,
                mechanism=mechanism, counterfactual=counterfactual,
                attribution_confidence=float(attribution_confidence), sample_size=int(sample_size),
                repetition_count=int(repetition_count), evidence=evidence,
            )
            assessment_id=f"cas-{uuid.uuid4().hex}"
            row=conn.execute(
                """INSERT INTO memory_causal_assessments(
                assessment_id,tenant_id,item_id,version_id,version_no,content_sha256,source_category,
                hypothesis,intervention,comparator,confounders,confounder_control,mechanism,counterfactual,
                attribution_confidence,sample_size,repetition_count,evidence,policy_version,decision_criteria,
                failure_reasons,created_by,occurred_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,
                %s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s) RETURNING eligible,observed_at""",
                (assessment_id,item['tenant_id'],item_id,version['version_id'],int(version['version_no']),version['content_sha256'],str(item['category']),
                 canonical(hypothesis),canonical(intervention),canonical(comparator),canonical(confounders),canonical(confounder_control),
                 canonical(mechanism),canonical(counterfactual),float(attribution_confidence),int(sample_size),int(repetition_count),canonical(evidence or {}),
                 CAUSAL_POLICY_VERSION,canonical(decision.criteria),canonical(list(decision.failure_reasons)),created_by,occurred),
            ).fetchone()
            db_eligible=bool(row['eligible'])
            if db_eligible != decision.eligible:
                raise RuntimeError('causal policy domain/database decision mismatch')
            self._audit(conn,'CAUSAL_ASSESSMENT_RECORDED',item_id,{
                'assessment_id':assessment_id,'version_id':str(version['version_id']),'version_no':int(version['version_no']),
                'content_sha256':str(version['content_sha256']),'policy_version':CAUSAL_POLICY_VERSION,
                'eligible':db_eligible,'failure_reasons':list(decision.failure_reasons),'created_by':created_by,
            })
        return {
            'assessment_id':assessment_id,'item_id':item_id,'version_id':str(version['version_id']),
            'version_no':int(version['version_no']),'content_sha256':str(version['content_sha256']),
            'source_category':'CORRELATION','policy_version':CAUSAL_POLICY_VERSION,'eligible':db_eligible,
            'criteria':decision.criteria,'failure_reasons':list(decision.failure_reasons),
            'occurred_at':occurred.isoformat(),'observed_at':row['observed_at'].isoformat(),
        }

    def list_causal_assessments(self, item_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows=conn.execute(
                """SELECT assessment_id,item_id,version_id,version_no,content_sha256,source_category,
                hypothesis,intervention,comparator,confounders,confounder_control,mechanism,counterfactual,
                attribution_confidence,sample_size,repetition_count,evidence,policy_version,decision_criteria,
                failure_reasons,eligible,created_by,occurred_at,observed_at,created_at
                FROM memory_causal_assessments WHERE item_id=%s ORDER BY observed_at DESC LIMIT %s""",
                (item_id,min(max(int(limit),1),500)),
            ).fetchall()
        result=[]
        for row in rows:
            x=dict(row)
            for key in ('occurred_at','observed_at','created_at'):
                if x.get(key) is not None:
                    x[key]=x[key].isoformat()
            result.append(x)
        return result

    def promote_cause(self, item_id: str, *, assessment_id: str, reason: str, actor_id_value: str) -> dict[str, Any]:
        require_canonical_mutation('causal.promote')
        if not str(reason or '').strip():
            raise ValueError('causal promotion reason is required')
        with self._connection() as conn:
            item=conn.execute(
                "SELECT category,content_sha256,validation_status,governor_eligible FROM memory_items WHERE item_id=%s FOR UPDATE",
                (item_id,),
            ).fetchone()
            if not item:
                raise KeyError(item_id)
            if str(item['category']) != 'CORRELATION':
                raise ValueError('causal promotion requires current CORRELATION memory')
            assessment=conn.execute(
                "SELECT assessment_id,version_id,version_no,content_sha256,eligible,failure_reasons,policy_version FROM memory_causal_assessments WHERE assessment_id=%s AND item_id=%s",
                (assessment_id,item_id),
            ).fetchone()
            if not assessment:
                raise KeyError(assessment_id)
            if not bool(assessment['eligible']):
                raise ValueError('causal assessment is not eligible for CAUSE promotion')
            current=conn.execute(
                "SELECT version_id,version_no,content_sha256 FROM memory_versions WHERE item_id=%s ORDER BY version_no DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            if not current or str(current['version_id'])!=str(assessment['version_id']) or str(current['content_sha256'])!=str(assessment['content_sha256']) or str(item['content_sha256'])!=str(assessment['content_sha256']):
                raise ConcurrencyConflict('causal assessment is stale; current memory version/hash changed')
            transition_id=f"trn-{uuid.uuid4().hex}"
            evidence={'causal_assessment_id':assessment_id,'causal_policy_version':CAUSAL_POLICY_VERSION}
            conn.execute(
                "SELECT memory_apply_ontology_transition(%s,%s,'CAUSE',%s,%s,%s::jsonb)",
                (transition_id,item_id,actor_id_value,str(reason).strip(),canonical(evidence)),
            )
            promotion=conn.execute(
                "SELECT promotion_id,promoted_at FROM memory_causal_promotions WHERE transition_id=%s",
                (transition_id,),
            ).fetchone()
            if not promotion:
                raise RuntimeError('causal promotion ledger row missing')
            self._audit(conn,'CAUSAL_CAUSE_PROMOTED',item_id,{
                'assessment_id':assessment_id,'promotion_id':str(promotion['promotion_id']),'transition_id':transition_id,
                'version_id':str(assessment['version_id']),'content_sha256':str(assessment['content_sha256']),
                'policy_version':CAUSAL_POLICY_VERSION,'actor_id':actor_id_value,
                'previous_validation_status':str(item.get('validation_status') or 'UNVALIDATED'),
                'previous_governor_eligible':bool(item.get('governor_eligible')),
            })
        return {
            'promotion_id':str(promotion['promotion_id']),'transition_id':transition_id,'assessment_id':assessment_id,
            'item_id':item_id,'from_category':'CORRELATION','to_category':'CAUSE','policy_version':CAUSAL_POLICY_VERSION,
            'version_id':str(assessment['version_id']),'content_sha256':str(assessment['content_sha256']),
            'validation_status':'UNVALIDATED','governor_eligible':False,'promoted_at':promotion['promoted_at'].isoformat(),
        }

    def _resolve_decision_mission_anchor(self, conn, mission_id: str) -> dict[str, Any]:
        session = conn.execute("""SELECT tenant_id,session_id,jsonb_build_object(
            'session_id',session_id,'identity',identity_json,'scope',scope,'objective',objective,
            'critical_rules',critical_rules,'operational_state',operational_state,
            'last_confirmed_action',last_confirmed_action,'blockers',blockers,'pending',pending,
            'next_safe_action',next_safe_action,'active_authorizations',active_authorizations,
            'required_memory_ids',to_jsonb(required_memory_ids),'updated_at',updated_at
          ) AS snapshot FROM sovereign_sessions WHERE session_id=%s""",(mission_id,)).fetchone()
        if session:
            return {"tenant_id":str(session["tenant_id"]),"anchor_type":"SESSION","anchor_id":str(session["session_id"]),"snapshot":session["snapshot"]}
        checkpoint = conn.execute("""SELECT tenant_id,checkpoint_id,jsonb_build_object(
            'checkpoint_id',checkpoint_id,'namespace',namespace,'mission_id',mission_id,
            'step_index',step_index,'state',state_json,'state_sha256',state_sha256,
            'project_id',project_id,'created_at',created_at
          ) AS snapshot FROM checkpoints WHERE mission_id=%s ORDER BY step_index DESC,created_at DESC LIMIT 1""",(mission_id,)).fetchone()
        if checkpoint:
            return {"tenant_id":str(checkpoint["tenant_id"]),"anchor_type":"CHECKPOINT","anchor_id":str(checkpoint["checkpoint_id"]),"snapshot":checkpoint["snapshot"]}
        raise KeyError(mission_id)

    @staticmethod
    def _iso_decision_row(row: dict[str, Any]) -> dict[str, Any]:
        value=dict(row)
        for key in ("occurred_at","observed_at","created_at"):
            if value.get(key) is not None:
                value[key]=value[key].astimezone(UTC).isoformat()
        return value

    def _load_decision_bundle(self, conn, decision_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        decision=conn.execute("SELECT * FROM sovereign_decisions WHERE decision_id=%s",(decision_id,)).fetchone()
        if not decision:
            raise KeyError(decision_id)
        evidence=conn.execute("""SELECT decision_evidence_id,role,item_id,version_id,version_no,content_sha256,category_snapshot,evidence_snapshot,created_at
            FROM sovereign_decision_evidence WHERE decision_id=%s ORDER BY role,item_id,version_id""",(decision_id,)).fetchall()
        outcomes=conn.execute("""SELECT decision_outcome_id,success,actual_outcome,proof,occurred_at,observed_at,recorded_by,created_at
            FROM sovereign_decision_outcomes WHERE decision_id=%s ORDER BY occurred_at,decision_outcome_id""",(decision_id,)).fetchall()
        replays=conn.execute("""SELECT replay_id,replay_sha256,requested_by,created_at FROM sovereign_decision_replays
            WHERE decision_id=%s ORDER BY created_at,replay_id""",(decision_id,)).fetchall()
        d=self._iso_decision_row(dict(decision))
        ev=[]
        for row in evidence:
            x=dict(row)
            if x.get("created_at") is not None: x["created_at"]=x["created_at"].isoformat()
            ev.append(x)
        outs=[]
        for row in outcomes:
            x=dict(row)
            for key in ("occurred_at","observed_at","created_at"):
                if x.get(key) is not None: x[key]=x[key].isoformat()
            outs.append(x)
        reps=[]
        for row in replays:
            x=dict(row)
            if x.get("created_at") is not None: x["created_at"]=x["created_at"].isoformat()
            reps.append(x)
        return d,ev,outs,reps

    def create_sovereign_decision(
        self, *, mission_id: str, criticality: str, objective: str, context: dict[str, Any],
        alternatives: list[dict[str, Any]], rationale: str, authority: dict[str, Any], action: dict[str, Any],
        expected_outcome: dict[str, Any], proof: dict[str, Any], evidence_refs: list[dict[str, Any]],
        created_by: str, occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        require_canonical_mutation('decision.create')
        mission=str(mission_id or '').strip()
        if not mission: raise ValueError("decision mission_id is required")
        normalized=validate_decision_record(
            objective=objective,alternatives=alternatives,rationale=rationale,action=action,
            expected_outcome=expected_outcome,proof=proof,evidence_refs=evidence_refs,criticality=criticality,
        )
        occurred=occurred_at or datetime.now(UTC)
        if occurred.tzinfo is None:
            raise ValueError("decision occurred_at must include timezone")
        occurred=occurred.astimezone(UTC)
        with self._connection() as conn:
            anchor=self._resolve_decision_mission_anchor(conn,mission)
            if str(anchor["tenant_id"]) != str(self.tenant_id):
                raise PermissionError("decision mission anchor is outside current tenant")
            resolved_refs=[]
            for raw in normalized["evidence_refs"]:
                item_id=str((raw or {}).get("item_id") or '').strip()
                role=str((raw or {}).get("role") or 'EVIDENCE').strip().upper()
                version_id=str((raw or {}).get("version_id") or '').strip()
                if not item_id: raise ValueError("decision evidence item_id is required")
                if version_id:
                    v=conn.execute("""SELECT v.version_id,m.tenant_id FROM memory_versions v JOIN memory_items m ON m.item_id=v.item_id
                        WHERE v.item_id=%s AND v.version_id=%s""",(item_id,version_id)).fetchone()
                else:
                    v=conn.execute("""SELECT v.version_id,m.tenant_id FROM memory_versions v JOIN memory_items m ON m.item_id=v.item_id
                        WHERE v.item_id=%s ORDER BY v.version_no DESC LIMIT 1""",(item_id,)).fetchone()
                if not v: raise KeyError(item_id)
                if str(v["tenant_id"]) != str(self.tenant_id): raise PermissionError("cross-tenant decision evidence forbidden")
                resolved_refs.append({"item_id":item_id,"version_id":str(v["version_id"]),"role":role})
            core=decision_core_material(
                mission_id=mission,mission_anchor_type=anchor["anchor_type"],mission_anchor_id=anchor["anchor_id"],
                mission_snapshot=anchor["snapshot"],criticality=normalized["criticality"],objective=normalized["objective"],
                context=dict(context or {}),alternatives=normalized["alternatives"],rationale=normalized["rationale"],
                authority=dict(authority or {}),action=normalized["action"],expected_outcome=normalized["expected_outcome"],
                proof=normalized["proof"],occurred_at=occurred.isoformat(),
            )
            core_sha=sha256_json(core)
            decision_id=f"dec-{uuid.uuid4().hex}"
            conn.execute("SELECT set_config('app.decision_mutation_authorized','1',true)")
            conn.execute("""INSERT INTO sovereign_decisions(
                decision_id,tenant_id,mission_id,mission_anchor_type,mission_anchor_id,mission_snapshot,criticality,
                objective,decision_context,alternatives,rationale,authority,action,expected_outcome,decision_proof,
                core_sha256,occurred_at,created_by)
                VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s)""",
                (decision_id,self.tenant_id,mission,anchor["anchor_type"],anchor["anchor_id"],canonical(anchor["snapshot"]),
                 normalized["criticality"],normalized["objective"],canonical(context or {}),canonical(normalized["alternatives"]),
                 normalized["rationale"],canonical(authority or {}),canonical(normalized["action"]),canonical(normalized["expected_outcome"]),
                 canonical(normalized["proof"]),core_sha,occurred,created_by))
            evidence_ids=[]
            for ref in resolved_refs:
                evidence_id=f"dev-{uuid.uuid4().hex}"
                conn.execute("""INSERT INTO sovereign_decision_evidence(
                    decision_evidence_id,tenant_id,decision_id,role,item_id,version_id,version_no,content_sha256,category_snapshot,evidence_snapshot)
                    VALUES(%s,%s,%s,%s,%s,%s,1,%s,'FACT','{}'::jsonb)""",
                    (evidence_id,self.tenant_id,decision_id,ref["role"],ref["item_id"],ref["version_id"],"0"*64))
                conn.execute("""INSERT INTO memory_experience_edges(edge_id,from_type,from_id,relation,to_type,to_id,evidence,occurred_at)
                    VALUES(%s,'DECISION',%s,'BASED_ON','MEMORY',%s,%s::jsonb,%s)""",
                    (f"edge-{uuid.uuid4().hex}",decision_id,ref["item_id"],canonical({"decision_evidence_id":evidence_id,"version_id":ref["version_id"],"role":ref["role"]}),occurred))
                evidence_ids.append(evidence_id)
            stored=conn.execute("SELECT * FROM sovereign_decisions WHERE decision_id=%s",(decision_id,)).fetchone()
            stored_core=decision_core_material(
                mission_id=str(stored["mission_id"]),mission_anchor_type=str(stored["mission_anchor_type"]),mission_anchor_id=str(stored["mission_anchor_id"]),
                mission_snapshot=stored["mission_snapshot"],criticality=str(stored["criticality"]),objective=str(stored["objective"]),
                context=stored["decision_context"],alternatives=stored["alternatives"],rationale=str(stored["rationale"]),authority=stored["authority"],
                action=stored["action"],expected_outcome=stored["expected_outcome"],proof=stored["decision_proof"],occurred_at=stored["occurred_at"].astimezone(UTC).isoformat(),
            )
            if sha256_json(stored_core) != str(stored["core_sha256"]):
                raise ConcurrencyConflict("decision mission snapshot changed during creation; retry against current sovereign anchor")
            conn.execute("SELECT set_config('app.decision_mutation_authorized','0',true)")
            self._audit(conn,"SOVEREIGN_DECISION_RECORDED",decision_id,{"mission_id":mission,"criticality":normalized["criticality"],"core_sha256":core_sha,"evidence_count":len(evidence_ids),"record_version":DECISION_RECORD_VERSION,"created_by":created_by})
            return {"decision_id":decision_id,"mission_id":mission,"criticality":normalized["criticality"],"core_sha256":core_sha,"record_version":DECISION_RECORD_VERSION,"evidence_count":len(evidence_ids),"occurred_at":occurred.isoformat()}

    def get_sovereign_decision(self, decision_id: str) -> dict[str, Any]:
        with self._connection() as conn:
            decision,evidence,outcomes,replays=self._load_decision_bundle(conn,decision_id)
        replay=build_replay_package(decision,evidence,outcomes)
        explanation={
            "objective":decision["objective"],"context":decision["decision_context"],"alternatives":decision["alternatives"],
            "evidence_used":evidence,"rationale":decision["rationale"],"authority":decision["authority"],
            "action":decision["action"],"expected_outcome":decision["expected_outcome"],"actual_outcomes":outcomes,
            "proof":decision["decision_proof"],"mission_snapshot":decision["mission_snapshot"],
        }
        return {"decision":decision,"explanation":explanation,"replay_package":replay,"replays":replays}

    def record_sovereign_decision_outcome(self, decision_id: str, *, success: bool, actual_outcome: dict[str, Any], proof: dict[str, Any], recorded_by: str, occurred_at: datetime | None = None) -> dict[str, Any]:
        require_canonical_mutation('decision.outcome')
        if not isinstance(actual_outcome,dict) or not actual_outcome: raise ValueError("decision actual_outcome must be a non-empty object")
        if not isinstance(proof,dict) or not proof: raise ValueError("decision outcome proof must be a non-empty object")
        occurred=occurred_at or datetime.now(UTC)
        if occurred.tzinfo is None:
            raise ValueError("decision outcome occurred_at must include timezone")
        occurred=occurred.astimezone(UTC)
        with self._connection() as conn:
            decision=conn.execute("SELECT occurred_at FROM sovereign_decisions WHERE decision_id=%s",(decision_id,)).fetchone()
            if not decision: raise KeyError(decision_id)
            if occurred < decision["occurred_at"]:
                raise ValueError("decision actual outcome cannot occur before the decision")
            outcome_id=f"dout-{uuid.uuid4().hex}"
            conn.execute("SELECT set_config('app.decision_mutation_authorized','1',true)")
            conn.execute("""INSERT INTO sovereign_decision_outcomes(decision_outcome_id,tenant_id,decision_id,success,actual_outcome,proof,occurred_at,recorded_by)
                VALUES(%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)""",(outcome_id,self.tenant_id,decision_id,bool(success),canonical(actual_outcome),canonical(proof),occurred,recorded_by))
            conn.execute("SELECT set_config('app.decision_mutation_authorized','0',true)")
            self._audit(conn,"SOVEREIGN_DECISION_OUTCOME_RECORDED",decision_id,{"decision_outcome_id":outcome_id,"success":bool(success),"recorded_by":recorded_by})
            return {"decision_outcome_id":outcome_id,"decision_id":decision_id,"success":bool(success),"occurred_at":occurred.isoformat()}

    def materialize_sovereign_decision_replay(self, decision_id: str, *, requested_by: str, reason: str) -> dict[str, Any]:
        require_canonical_mutation('decision.replay')
        if not str(reason or '').strip(): raise ValueError("decision replay reason is required")
        with self._connection() as conn:
            decision,evidence,outcomes,_=self._load_decision_bundle(conn,decision_id)
            package=build_replay_package(decision,evidence,outcomes)
            replay_id=f"drp-{uuid.uuid4().hex}"
            stored={**package,"materialization_reason":str(reason).strip()}
            conn.execute("SELECT set_config('app.decision_mutation_authorized','1',true)")
            conn.execute("""INSERT INTO sovereign_decision_replays(replay_id,tenant_id,decision_id,replay_sha256,replay_package,requested_by)
                VALUES(%s,%s,%s,%s,%s::jsonb,%s)""",(replay_id,self.tenant_id,decision_id,package["replay_sha256"],canonical(stored),requested_by))
            conn.execute("SELECT set_config('app.decision_mutation_authorized','0',true)")
            self._audit(conn,"SOVEREIGN_DECISION_REPLAY_MATERIALIZED",decision_id,{"replay_id":replay_id,"replay_sha256":package["replay_sha256"],"requested_by":requested_by,"reason":str(reason).strip()})
            return {"replay_id":replay_id,"decision_id":decision_id,"replay_sha256":package["replay_sha256"],"execution_mode":"MATERIALIZED_NO_SIDE_EFFECT","replay_package":package}

    @staticmethod
    def _economic_iso(value: dict[str, Any]) -> dict[str, Any]:
        out=dict(value)
        for key in ("occurred_at","observed_at","valid_from","valid_to","created_at"):
            if out.get(key) is not None and hasattr(out[key],"isoformat"):
                out[key]=out[key].isoformat()
        for key in ("value","weight"):
            if out.get(key) is not None:
                out[key]=format(out[key],"f") if hasattr(out[key],"as_tuple") else str(out[key])
        return out

    def _economic_source_snapshot(self, conn, *, source_kind: str, source_id: str, mission_id: str) -> tuple[dict[str, Any], str]:
        kind=str(source_kind).strip().upper()
        sid=str(source_id).strip()
        if kind == "SOVEREIGN_DECISION":
            row=conn.execute("""SELECT decision_id,tenant_id,mission_id,criticality,objective,authority,action,expected_outcome,core_sha256,occurred_at,observed_at,created_at
                FROM sovereign_decisions WHERE decision_id=%s""",(sid,)).fetchone()
            if not row: raise KeyError(sid)
            if str(row['tenant_id'])!=self.tenant_id or str(row['mission_id'])!=mission_id:
                raise PermissionError("economic decision attribution scope mismatch")
            snap=self._economic_iso(dict(row))
        elif kind in {"EXPERIENCE_INTERVENTION","EXPERIENCE_EVIDENCE"}:
            row=conn.execute("""SELECT node_id,tenant_id,mission_id,node_type,entity_ref,memory_item_id,memory_version_id,memory_content_sha256,memory_category_snapshot,payload,provenance,occurred_at,observed_at,created_at
                FROM experience_graph_nodes WHERE node_id=%s""",(sid,)).fetchone()
            if not row: raise KeyError(sid)
            expected="INTERVENTION" if kind=="EXPERIENCE_INTERVENTION" else "EVIDENCE"
            if str(row['tenant_id'])!=self.tenant_id or str(row['mission_id'])!=mission_id:
                raise PermissionError("economic experience attribution scope mismatch")
            if str(row['node_type'])!=expected:
                raise ValueError(f"economic attribution {kind} requires {expected} node")
            snap=self._economic_iso(dict(row))
        elif kind == "ECONOMIC_ENTITY":
            row=conn.execute("SELECT * FROM economic_entities WHERE economic_entity_id=%s",(sid,)).fetchone()
            if not row: raise KeyError(sid)
            if str(row['tenant_id'])!=self.tenant_id: raise PermissionError("economic entity attribution tenant mismatch")
            snap=self._economic_iso(dict(row))
        elif kind == "ECONOMIC_STATE":
            row=conn.execute("SELECT * FROM economic_states WHERE economic_state_id=%s",(sid,)).fetchone()
            if not row: raise KeyError(sid)
            if str(row['tenant_id'])!=self.tenant_id: raise PermissionError("economic state attribution tenant mismatch")
            if row.get('mission_id') is not None and str(row['mission_id'])!=mission_id:
                raise PermissionError("economic state attribution mission mismatch")
            snap=self._economic_iso(dict(row))
        else:
            raise ValueError("invalid economic attribution source_kind")
        material={k:v for k,v in snap.items() if k!='tenant_id'}
        return material,sha256_json(material)

    def create_economic_entity(self, *, entity_type: str, external_ref: str, attributes: dict[str, Any], created_by: str,
        parent_entity_id: str | None = None, occurred_at: datetime | None = None, observed_at: datetime | None = None,
        valid_from: datetime | None = None, valid_to: datetime | None = None) -> dict[str, Any]:
        require_canonical_mutation('economic.entity')
        record=validate_entity_record(entity_type=entity_type,external_ref=external_ref,attributes=attributes)
        temporal=normalize_temporal_envelope(occurred_at=occurred_at,observed_at=observed_at,valid_from=valid_from,valid_to=valid_to)
        entity_id=f"eco-{uuid.uuid4().hex}"
        with self._connection() as conn:
            if record['entity_type'] in {'PRODUCT','CAMPAIGN'} and parent_entity_id is not None:
                raise ValueError(f"{record['entity_type']} economic entity cannot have parent")
            if record['entity_type'] in {'SKU','AD'} and not parent_entity_id:
                raise ValueError(f"{record['entity_type']} economic entity requires parent")
            if parent_entity_id:
                parent=conn.execute("SELECT tenant_id,entity_type FROM economic_entities WHERE economic_entity_id=%s",(parent_entity_id,)).fetchone()
                if not parent:
                    raise KeyError(parent_entity_id)
                if str(parent['tenant_id']) != self.tenant_id:
                    raise PermissionError('cross-tenant economic parent forbidden')
                expected='PRODUCT' if record['entity_type']=='SKU' else 'CAMPAIGN'
                if str(parent['entity_type']) != expected:
                    raise ValueError(f"{record['entity_type']} parent must be {expected}")
            conn.execute("SELECT set_config('app.economic_mutation_authorized','1',true)")
            conn.execute("""INSERT INTO economic_entities(economic_entity_id,tenant_id,entity_type,external_ref,parent_entity_id,attributes,occurred_at,observed_at,valid_from,valid_to,created_by)
                VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)""",
                (entity_id,self.tenant_id,record['entity_type'],record['external_ref'],parent_entity_id,canonical(record['attributes']),temporal.occurred_at,temporal.observed_at,temporal.valid_from,temporal.valid_to,created_by))
            conn.execute("SELECT set_config('app.economic_mutation_authorized','0',true)")
            self._audit(conn,'ECONOMIC_ENTITY_RECORDED',entity_id,{'entity_type':record['entity_type'],'external_ref':record['external_ref'],'parent_entity_id':parent_entity_id,'temporal':temporal.as_dict(),'created_by':created_by})
        return {'economic_entity_id':entity_id,'entity_type':record['entity_type'],'external_ref':record['external_ref'],'parent_entity_id':parent_entity_id,**temporal.as_dict()}

    def record_economic_state(self, *, economic_entity_id: str, state_type: str, value: Any, unit: str, currency: str | None,
        metadata: dict[str, Any], created_by: str, mission_id: str | None = None, occurred_at: datetime | None = None,
        observed_at: datetime | None = None, valid_from: datetime | None = None, valid_to: datetime | None = None) -> dict[str, Any]:
        require_canonical_mutation('economic.state')
        record=validate_state_record(state_type=state_type,value=value,unit=unit,currency=currency,metadata=metadata)
        temporal=normalize_temporal_envelope(occurred_at=occurred_at,observed_at=observed_at,valid_from=valid_from,valid_to=valid_to)
        state_id=f"ecs-{uuid.uuid4().hex}"
        with self._connection() as conn:
            if not conn.execute("SELECT 1 FROM economic_entities WHERE economic_entity_id=%s",(economic_entity_id,)).fetchone():
                raise KeyError(economic_entity_id)
            conn.execute("SELECT set_config('app.economic_mutation_authorized','1',true)")
            conn.execute("""INSERT INTO economic_states(economic_state_id,tenant_id,economic_entity_id,mission_id,state_type,value,unit,currency,state_payload,occurred_at,observed_at,valid_from,valid_to,created_by)
                VALUES(%s,%s,%s,%s,%s,%s::numeric,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)""",
                (state_id,self.tenant_id,economic_entity_id,str(mission_id).strip() if mission_id else None,record['state_type'],record['value'],record['unit'],record['currency'],canonical(record['metadata']),temporal.occurred_at,temporal.observed_at,temporal.valid_from,temporal.valid_to,created_by))
            conn.execute("SELECT set_config('app.economic_mutation_authorized','0',true)")
            self._audit(conn,'ECONOMIC_STATE_RECORDED',state_id,{'economic_entity_id':economic_entity_id,'mission_id':mission_id,'state_type':record['state_type'],'value':record['value'],'unit':record['unit'],'currency':record['currency'],'temporal':temporal.as_dict(),'created_by':created_by})
        return {'economic_state_id':state_id,'economic_entity_id':economic_entity_id,'mission_id':mission_id,**record,**temporal.as_dict()}

    def record_economic_result(self, *, mission_id: str, economic_entity_id: str | None, metric_type: str, value: Any, unit: str,
        currency: str | None, proof: dict[str, Any], attributions: list[dict[str, Any]], created_by: str,
        experience_result_node_id: str | None = None, occurred_at: datetime | None = None, observed_at: datetime | None = None,
        valid_from: datetime | None = None, valid_to: datetime | None = None) -> dict[str, Any]:
        require_canonical_mutation('economic.result')
        record=validate_result_record(mission_id=mission_id,entity_id=economic_entity_id,metric_type=metric_type,value=value,unit=unit,currency=currency,proof=proof,attributions=attributions)
        temporal=normalize_temporal_envelope(occurred_at=occurred_at,observed_at=observed_at,valid_from=valid_from,valid_to=valid_to)
        result_id=f"ecr-{uuid.uuid4().hex}"
        with self._connection() as conn:
            if economic_entity_id and not conn.execute("SELECT 1 FROM economic_entities WHERE economic_entity_id=%s",(economic_entity_id,)).fetchone():
                raise KeyError(economic_entity_id)
            resolved=[]
            for attr in record['attributions']:
                snapshot,digest=self._economic_source_snapshot(conn,source_kind=attr['source_kind'],source_id=attr['source_id'],mission_id=record['mission_id'])
                resolved.append({**attr,'snapshot':snapshot,'source_sha256':digest})
            conn.execute("SELECT set_config('app.economic_mutation_authorized','1',true)")
            conn.execute("""INSERT INTO economic_results(economic_result_id,tenant_id,mission_id,economic_entity_id,metric_type,value,unit,currency,experience_result_node_id,proof,occurred_at,observed_at,valid_from,valid_to,created_by)
                VALUES(%s,%s,%s,%s,%s,%s::numeric,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)""",
                (result_id,self.tenant_id,record['mission_id'],economic_entity_id,record['metric_type'],record['value'],record['unit'],record['currency'],experience_result_node_id,canonical(record['proof']),temporal.occurred_at,temporal.observed_at,temporal.valid_from,temporal.valid_to,created_by))
            attr_ids=[]
            for attr in resolved:
                attr_id=f"eca-{uuid.uuid4().hex}"
                conn.execute("""INSERT INTO economic_attributions(economic_attribution_id,tenant_id,economic_result_id,source_kind,source_id,weight,rationale,evidence,source_snapshot,source_sha256,occurred_at,observed_at,valid_from,valid_to,created_by)
                    VALUES(%s,%s,%s,%s,%s,%s::numeric,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s)""",
                    (attr_id,self.tenant_id,result_id,attr['source_kind'],attr['source_id'],attr['weight'],attr['rationale'],canonical(attr['evidence']),canonical(attr['snapshot']),attr['source_sha256'],temporal.occurred_at,temporal.observed_at,temporal.valid_from,temporal.valid_to,created_by))
                attr_ids.append(attr_id)
            conn.execute("SELECT set_config('app.economic_mutation_authorized','0',true)")
            self._audit(conn,'ECONOMIC_RESULT_RECORDED',result_id,{'mission_id':record['mission_id'],'economic_entity_id':economic_entity_id,'metric_type':record['metric_type'],'value':record['value'],'unit':record['unit'],'currency':record['currency'],'experience_result_node_id':experience_result_node_id,'attributions':[{'source_kind':x['source_kind'],'source_id':x['source_id'],'weight':x['weight'],'source_sha256':x['source_sha256']} for x in resolved],'temporal':temporal.as_dict(),'created_by':created_by})
        return {'economic_result_id':result_id,'mission_id':record['mission_id'],'economic_entity_id':economic_entity_id,'metric_type':record['metric_type'],'value':record['value'],'unit':record['unit'],'currency':record['currency'],'experience_result_node_id':experience_result_node_id,'attribution_ids':attr_ids,'attribution_count':len(attr_ids),**temporal.as_dict()}

    def get_economic_result(self, economic_result_id: str) -> dict[str, Any]:
        with self._connection() as conn:
            row=conn.execute("SELECT * FROM economic_results WHERE economic_result_id=%s",(economic_result_id,)).fetchone()
            if not row: raise KeyError(economic_result_id)
            attrs=conn.execute("SELECT * FROM economic_attributions WHERE economic_result_id=%s ORDER BY economic_attribution_id",(economic_result_id,)).fetchall()
        result=self._economic_iso(dict(row))
        return {'result':result,'attributions':[self._economic_iso(dict(x)) for x in attrs]}

    def economic_history(self, *, economic_entity_id: str | None = None, mission_id: str | None = None,
        valid_at: datetime | None = None, known_at: datetime | None = None, limit: int = 200) -> dict[str, Any]:
        valid_moment=normalize_as_of(valid_at,'valid_at')
        known_moment=normalize_as_of(known_at,'known_at')
        state_clauses=["memory_bitemporal_visible(valid_from,valid_to,observed_at,created_at,%s,%s)"]
        state_params: list[Any]=[valid_moment,known_moment]
        result_clauses=["memory_bitemporal_visible(valid_from,valid_to,observed_at,created_at,%s,%s)"]
        result_params: list[Any]=[valid_moment,known_moment]
        if economic_entity_id:
            state_clauses.append("economic_entity_id=%s"); state_params.append(economic_entity_id)
            result_clauses.append("economic_entity_id=%s"); result_params.append(economic_entity_id)
        if mission_id:
            state_clauses.append("mission_id=%s"); state_params.append(mission_id)
            result_clauses.append("mission_id=%s"); result_params.append(mission_id)
        cap=min(max(int(limit),1),500)
        state_params.append(cap); result_params.append(cap)
        with self._connection() as conn:
            # Dynamic SQL fragments below are fixed internal literals; caller values remain psycopg parameters.
            states=conn.execute(f"SELECT * FROM economic_states WHERE {' AND '.join(state_clauses)} ORDER BY occurred_at,observed_at,economic_state_id LIMIT %s",tuple(state_params)).fetchall()  # nosec B608
            # Dynamic SQL fragments below are fixed internal literals; caller values remain psycopg parameters.
            results=conn.execute(f"SELECT * FROM economic_results WHERE {' AND '.join(result_clauses)} ORDER BY occurred_at,observed_at,economic_result_id LIMIT %s",tuple(result_params)).fetchall()  # nosec B608
        return {'economic_entity_id':economic_entity_id,'mission_id':mission_id,'valid_at':valid_moment.isoformat(),'known_at':known_moment.isoformat(),'states':[self._economic_iso(dict(x)) for x in states],'results':[self._economic_iso(dict(x)) for x in results]}

    @staticmethod
    def _operational_iso(value: dict[str, Any]) -> dict[str, Any]:
        out=dict(value)
        for key in ("occurred_at","observed_at","valid_from","valid_to","executed_at","created_at","status_recorded_at"):
            if out.get(key) is not None and hasattr(out[key],"isoformat"):
                out[key]=out[key].isoformat()
        return out

    def _operational_current_status_in_conn(self, conn, skill_version_id: str) -> str:
        row=conn.execute("SELECT status FROM operational_status_events WHERE skill_version_id=%s ORDER BY created_at DESC,status_event_id DESC LIMIT 1",(skill_version_id,)).fetchone()
        return str(row['status']) if row else 'UNPROVEN'

    def _operational_proof_gate_ready_in_conn(self, conn, skill_version_id: str) -> bool:
        gate=conn.execute("SELECT created_at FROM operational_status_events WHERE skill_version_id=%s AND status IN ('STALE','FAILED') ORDER BY created_at DESC,status_event_id DESC LIMIT 1",(skill_version_id,)).fetchone()
        gate_at=gate['created_at'] if gate else None
        ready=[]
        for proof_type in ('REPLAY','RECOVERY'):
            if gate_at is None:
                row=conn.execute("SELECT result FROM operational_proofs WHERE skill_version_id=%s AND proof_type=%s ORDER BY created_at DESC,proof_id DESC LIMIT 1",(skill_version_id,proof_type)).fetchone()
            else:
                row=conn.execute("SELECT result FROM operational_proofs WHERE skill_version_id=%s AND proof_type=%s AND created_at>%s ORDER BY created_at DESC,proof_id DESC LIMIT 1",(skill_version_id,proof_type,gate_at)).fetchone()
            ready.append(bool(row and str(row['result'])=='PASS'))
        return all(ready)

    def _append_operational_status_in_conn(self, conn, *, skill_version_id: str, status: str, reason: str,
        evidence: dict[str, Any], created_by: str, trigger_proof_id: str | None = None,
        occurred_at: datetime | None = None) -> dict[str, Any]:
        require_canonical_mutation("operational.status.append")
        record=validate_status_record(status=status,reason=reason,evidence=evidence)
        temporal=normalize_temporal_envelope(occurred_at=occurred_at)
        event_id=f"ops-{uuid.uuid4().hex}"
        conn.execute("""INSERT INTO operational_status_events(status_event_id,tenant_id,skill_version_id,status,reason,evidence,trigger_proof_id,occurred_at,observed_at,valid_from,valid_to,created_by)
            VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s)""",
            (event_id,self.tenant_id,skill_version_id,record['status'],record['reason'],canonical(record['evidence']),trigger_proof_id,
             temporal.occurred_at,temporal.observed_at,temporal.valid_from,temporal.valid_to,created_by))
        return {'status_event_id':event_id,'skill_version_id':skill_version_id,**record,**temporal.as_dict()}

    def create_operational_competency(self, *, competency_key: str, title: str, description: str, domain: str,
        created_by: str, occurred_at: datetime | None = None, observed_at: datetime | None = None,
        valid_from: datetime | None = None, valid_to: datetime | None = None) -> dict[str, Any]:
        require_canonical_mutation('operational.competency')
        record=validate_competency_record(competency_key=competency_key,title=title,description=description,domain=domain)
        temporal=normalize_temporal_envelope(occurred_at=occurred_at,observed_at=observed_at,valid_from=valid_from,valid_to=valid_to)
        competency_id=f"ocp-{uuid.uuid4().hex}"
        with self._connection() as conn:
            conn.execute("SELECT set_config('app.operational_mutation_authorized','1',true)")
            conn.execute("""INSERT INTO operational_competencies(competency_id,tenant_id,competency_key,title,description,domain,occurred_at,observed_at,valid_from,valid_to,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (competency_id,self.tenant_id,record['competency_key'],record['title'],record['description'],record['domain'],
                 temporal.occurred_at,temporal.observed_at,temporal.valid_from,temporal.valid_to,created_by))
            conn.execute("SELECT set_config('app.operational_mutation_authorized','0',true)")
            self._audit(conn,'OPERATIONAL_COMPETENCY_RECORDED',competency_id,{**record,'created_by':created_by,'temporal':temporal.as_dict()})
        return {'competency_id':competency_id,**record,**temporal.as_dict()}

    def create_operational_skill(self, *, competency_id: str, skill_key: str, title: str, description: str,
        created_by: str, occurred_at: datetime | None = None, observed_at: datetime | None = None,
        valid_from: datetime | None = None, valid_to: datetime | None = None) -> dict[str, Any]:
        require_canonical_mutation('operational.skill')
        record=validate_skill_record(skill_key=skill_key,title=title,description=description)
        temporal=normalize_temporal_envelope(occurred_at=occurred_at,observed_at=observed_at,valid_from=valid_from,valid_to=valid_to)
        skill_id=f"osk-{uuid.uuid4().hex}"
        with self._connection() as conn:
            if not conn.execute("SELECT 1 FROM operational_competencies WHERE competency_id=%s",(competency_id,)).fetchone(): raise KeyError(competency_id)
            conn.execute("SELECT set_config('app.operational_mutation_authorized','1',true)")
            conn.execute("""INSERT INTO operational_skills(skill_id,tenant_id,competency_id,skill_key,title,description,occurred_at,observed_at,valid_from,valid_to,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (skill_id,self.tenant_id,competency_id,record['skill_key'],record['title'],record['description'],
                 temporal.occurred_at,temporal.observed_at,temporal.valid_from,temporal.valid_to,created_by))
            conn.execute("SELECT set_config('app.operational_mutation_authorized','0',true)")
            self._audit(conn,'OPERATIONAL_SKILL_RECORDED',skill_id,{'competency_id':competency_id,**record,'created_by':created_by,'temporal':temporal.as_dict()})
        return {'skill_id':skill_id,'competency_id':competency_id,**record,**temporal.as_dict()}

    def create_operational_skill_version(self, *, skill_id: str, version_label: str, implementation_version: str,
        implementation_sha256: str, contract: dict[str, Any], created_by: str, supersedes_skill_version_id: str | None = None,
        occurred_at: datetime | None = None, observed_at: datetime | None = None,
        valid_from: datetime | None = None, valid_to: datetime | None = None) -> dict[str, Any]:
        require_canonical_mutation('operational.skill_version')
        record=validate_skill_version_record(version_label=version_label,implementation_version=implementation_version,
            implementation_sha256=implementation_sha256,contract=contract)
        temporal=normalize_temporal_envelope(occurred_at=occurred_at,observed_at=observed_at,valid_from=valid_from,valid_to=valid_to)
        version_id=f"osv-{uuid.uuid4().hex}"
        stale_event=None
        with self._connection() as conn:
            if not conn.execute("SELECT 1 FROM operational_skills WHERE skill_id=%s",(skill_id,)).fetchone(): raise KeyError(skill_id)
            if supersedes_skill_version_id:
                previous=conn.execute("SELECT skill_id FROM operational_skill_versions WHERE skill_version_id=%s",(supersedes_skill_version_id,)).fetchone()
                if not previous: raise KeyError(supersedes_skill_version_id)
                if str(previous['skill_id'])!=skill_id: raise ValueError('superseded skill version must belong to same skill')
            conn.execute("SELECT set_config('app.operational_mutation_authorized','1',true)")
            conn.execute("""INSERT INTO operational_skill_versions(skill_version_id,tenant_id,skill_id,version_label,implementation_version,implementation_sha256,contract_json,supersedes_skill_version_id,occurred_at,observed_at,valid_from,valid_to,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s)""",
                (version_id,self.tenant_id,skill_id,record['version_label'],record['implementation_version'],record['implementation_sha256'],canonical(record['contract']),supersedes_skill_version_id,
                 temporal.occurred_at,temporal.observed_at,temporal.valid_from,temporal.valid_to,created_by))
            if supersedes_skill_version_id and self._operational_current_status_in_conn(conn,supersedes_skill_version_id)=='PROVEN':
                stale_event=self._append_operational_status_in_conn(conn,skill_version_id=supersedes_skill_version_id,status='STALE',
                    reason=f'superseded by {version_id}',evidence={'superseded_by':version_id,'new_version_label':record['version_label']},created_by=created_by)
            conn.execute("SELECT set_config('app.operational_mutation_authorized','0',true)")
            self._audit(conn,'OPERATIONAL_SKILL_VERSION_RECORDED',version_id,{'skill_id':skill_id,**record,'supersedes_skill_version_id':supersedes_skill_version_id,'staled_previous':bool(stale_event),'created_by':created_by,'temporal':temporal.as_dict()})
        return {'skill_version_id':version_id,'skill_id':skill_id,**record,'supersedes_skill_version_id':supersedes_skill_version_id,'stale_event':stale_event,'current_status':'UNPROVEN',**temporal.as_dict()}

    def add_operational_capability(self, *, skill_version_id: str, capability_key: str, contract: dict[str, Any],
        created_by: str, occurred_at: datetime | None = None, observed_at: datetime | None = None,
        valid_from: datetime | None = None, valid_to: datetime | None = None) -> dict[str, Any]:
        require_canonical_mutation('operational.capability')
        record=validate_capability_record(capability_key=capability_key,contract=contract)
        temporal=normalize_temporal_envelope(occurred_at=occurred_at,observed_at=observed_at,valid_from=valid_from,valid_to=valid_to)
        capability_id=f"ocb-{uuid.uuid4().hex}"
        with self._connection() as conn:
            if not conn.execute("SELECT 1 FROM operational_skill_versions WHERE skill_version_id=%s",(skill_version_id,)).fetchone(): raise KeyError(skill_version_id)
            conn.execute("SELECT set_config('app.operational_mutation_authorized','1',true)")
            conn.execute("""INSERT INTO operational_capabilities(capability_id,tenant_id,skill_version_id,capability_key,contract_json,occurred_at,observed_at,valid_from,valid_to,created_by)
                VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s)""",
                (capability_id,self.tenant_id,skill_version_id,record['capability_key'],canonical(record['contract']),temporal.occurred_at,temporal.observed_at,temporal.valid_from,temporal.valid_to,created_by))
            conn.execute("SELECT set_config('app.operational_mutation_authorized','0',true)")
            self._audit(conn,'OPERATIONAL_CAPABILITY_RECORDED',capability_id,{'skill_version_id':skill_version_id,**record,'created_by':created_by,'temporal':temporal.as_dict()})
        return {'capability_id':capability_id,'skill_version_id':skill_version_id,**record,**temporal.as_dict()}

    def record_operational_proof(self, *, skill_version_id: str, proof_type: str, result: str, artifact_ref: str,
        artifact_sha256: str, evidence: dict[str, Any], created_by: str, executed_at: datetime | None = None,
        occurred_at: datetime | None = None, observed_at: datetime | None = None,
        valid_from: datetime | None = None, valid_to: datetime | None = None) -> dict[str, Any]:
        require_canonical_mutation('operational.proof')
        record=validate_proof_record(proof_type=proof_type,result=result,artifact_ref=artifact_ref,artifact_sha256=artifact_sha256,evidence=evidence)
        temporal=normalize_temporal_envelope(occurred_at=occurred_at or executed_at,observed_at=observed_at,valid_from=valid_from,valid_to=valid_to)
        executed=executed_at or temporal.occurred_at
        if executed.tzinfo is None: raise ValueError('executed_at must include timezone')
        proof_id=f"opf-{uuid.uuid4().hex}"
        status_event=None
        with self._connection() as conn:
            if not conn.execute("SELECT 1 FROM operational_skill_versions WHERE skill_version_id=%s",(skill_version_id,)).fetchone(): raise KeyError(skill_version_id)
            conn.execute("SELECT set_config('app.operational_mutation_authorized','1',true)")
            conn.execute("""INSERT INTO operational_proofs(proof_id,tenant_id,skill_version_id,proof_type,result,artifact_ref,artifact_sha256,evidence,executed_at,occurred_at,observed_at,valid_from,valid_to,created_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s)""",
                (proof_id,self.tenant_id,skill_version_id,record['proof_type'],record['result'],record['artifact_ref'],record['artifact_sha256'],canonical(record['evidence']),executed,
                 temporal.occurred_at,temporal.observed_at,temporal.valid_from,temporal.valid_to,created_by))
            current=self._operational_current_status_in_conn(conn,skill_version_id)
            if record['result']=='FAIL':
                status_event=self._append_operational_status_in_conn(conn,skill_version_id=skill_version_id,status='FAILED',
                    reason=f"{record['proof_type']} proof failed",evidence={'proof_id':proof_id,'artifact_sha256':record['artifact_sha256']},created_by=created_by,trigger_proof_id=proof_id,occurred_at=executed)
                current='FAILED'
            elif self._operational_proof_gate_ready_in_conn(conn,skill_version_id) and current!='PROVEN':
                status_event=self._append_operational_status_in_conn(conn,skill_version_id=skill_version_id,status='PROVEN',
                    reason='required replay and recovery proofs passed',evidence={'trigger_proof_id':proof_id,'proof_gate':'REPLAY+RECOVERY'},created_by=created_by,trigger_proof_id=proof_id,occurred_at=executed)
                current='PROVEN'
            conn.execute("SELECT set_config('app.operational_mutation_authorized','0',true)")
            self._audit(conn,'OPERATIONAL_PROOF_RECORDED',proof_id,{'skill_version_id':skill_version_id,**record,'auto_status':current,'status_event_id':status_event['status_event_id'] if status_event else None,'created_by':created_by})
        return {'proof_id':proof_id,'skill_version_id':skill_version_id,**record,'executed_at':executed.isoformat(),'current_status':current,'status_event':status_event,**temporal.as_dict()}

    def set_operational_status(self, *, skill_version_id: str, status: str, reason: str, evidence: dict[str, Any],
        created_by: str, occurred_at: datetime | None = None) -> dict[str, Any]:
        require_canonical_mutation('operational.status')
        requested_status=str(status).strip().upper()
        if requested_status in {'PROVEN','FAILED'}:
            raise ValueError(f'{requested_status} status is proof-engine managed and cannot be asserted directly')
        with self._connection() as conn:
            if not conn.execute("SELECT 1 FROM operational_skill_versions WHERE skill_version_id=%s",(skill_version_id,)).fetchone(): raise KeyError(skill_version_id)
            conn.execute("SELECT set_config('app.operational_mutation_authorized','1',true)")
            event=self._append_operational_status_in_conn(conn,skill_version_id=skill_version_id,status=status,reason=reason,evidence=evidence,created_by=created_by,occurred_at=occurred_at)
            conn.execute("SELECT set_config('app.operational_mutation_authorized','0',true)")
            self._audit(conn,'OPERATIONAL_STATUS_RECORDED',event['status_event_id'],{'skill_version_id':skill_version_id,'status':event['status'],'reason':event['reason'],'created_by':created_by})
        return event

    def get_operational_skill_version(self, skill_version_id: str) -> dict[str, Any]:
        with self._connection() as conn:
            row=conn.execute("""SELECT c.competency_id,c.competency_key,c.title competency_title,c.domain,s.skill_id,s.skill_key,s.title skill_title,
                v.* FROM operational_skill_versions v JOIN operational_skills s ON s.skill_id=v.skill_id JOIN operational_competencies c ON c.competency_id=s.competency_id WHERE v.skill_version_id=%s""",(skill_version_id,)).fetchone()
            if not row: raise KeyError(skill_version_id)
            capabilities=conn.execute("SELECT * FROM operational_capabilities WHERE skill_version_id=%s ORDER BY capability_key,created_at",(skill_version_id,)).fetchall()
            proofs=conn.execute("SELECT * FROM operational_proofs WHERE skill_version_id=%s ORDER BY created_at,proof_id",(skill_version_id,)).fetchall()
            statuses=conn.execute("SELECT * FROM operational_status_events WHERE skill_version_id=%s ORDER BY created_at,status_event_id",(skill_version_id,)).fetchall()
            current=self._operational_current_status_in_conn(conn,skill_version_id)
        return {'skill_version':self._operational_iso(dict(row)),'current_status':current,
                'capabilities':[self._operational_iso(dict(x)) for x in capabilities],
                'proofs':[self._operational_iso(dict(x)) for x in proofs],
                'status_history':[self._operational_iso(dict(x)) for x in statuses]}

    def operational_catalog(self, *, status: str | None = None, competency_key: str | None = None,
        capability_key: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        clauses=['1=1']; params:list[Any]=[]
        if status:
            state=str(status).strip().upper()
            if state not in {'UNPROVEN','PROVEN','STALE','FAILED','DEPRECATED'}: raise ValueError('invalid operational catalog status')
            clauses.append('c.current_status=%s'); params.append(state)
        if competency_key:
            clauses.append('c.competency_key=%s'); params.append(str(competency_key).strip().upper())
        if capability_key:
            clauses.append("EXISTS(SELECT 1 FROM operational_capabilities cp WHERE cp.skill_version_id=c.skill_version_id AND cp.capability_key=%s)")
            params.append(str(capability_key).strip().upper())
        params.append(min(max(int(limit),1),500))
        with self._connection() as conn:
            # Dynamic SQL fragments below are fixed internal literals; caller values remain psycopg parameters.
            rows=conn.execute(f"SELECT c.* FROM operational_skill_catalog c WHERE {' AND '.join(clauses)} ORDER BY c.competency_key,c.skill_key,c.version_created_at DESC LIMIT %s",tuple(params)).fetchall()  # nosec B608
        return [self._operational_iso(dict(x)) for x in rows]

    def list_memories(self, *, query: str | None = None, operator_class: str | None = None, memory_scope: str | None = None, memory_scope_ref: str | None = None, valid_at: datetime | None = None, known_at: datetime | None = None, limit: int = 100) -> list[dict[str, Any]]:
        valid_moment = normalize_as_of(valid_at, "valid_at")
        known_moment = normalize_as_of(known_at, "known_at")
        clauses = ["memory_bitemporal_visible(m.valid_from,m.valid_to,m.observed_at,m.created_at,%s,%s)"]
        params: list[Any] = [valid_moment, known_moment]
        if query:
            clauses.append("(m.search_vector @@ plainto_tsquery('simple',%s) OR m.memory_key ILIKE %s OR m.content_text ILIKE %s)")
            params.extend([query, f"%{query}%", f"%{query}%"])
        if operator_class:
            clauses.append("s.operator_class=%s")
            params.append(operator_class)
        if memory_scope is not None:
            semantic_scope = self.access.validate_memory_scope(memory_scope, memory_scope_ref=memory_scope_ref)
            clauses.append("m.memory_scope=%s")
            params.append(semantic_scope["memory_scope"])
            if semantic_scope["memory_scope"] != "GLOBAL_USER":
                clauses.append("m.memory_scope_ref=%s")
                params.append(semantic_scope["memory_scope_ref"])
        elif memory_scope_ref is not None:
            raise ValueError("memory_scope_ref requires memory_scope")
        params.append(min(max(int(limit), 1), 500))
        sql_query = pg_sql.SQL("""
        SELECT m.item_id,m.namespace,m.memory_key,m.category,m.content_text,m.provenance,m.confidence,m.source,m.tags,
               m.memory_scope,m.memory_scope_ref,m.sharing_scope,m.owner_user_id,m.owner_agent_id,m.project_id,m.team_id,m.organization_id,
               m.occurred_at,m.observed_at,m.valid_from,m.valid_to,m.created_at,m.last_used_at,m.retrieval_count,m.application_count,m.success_count,m.failure_count,
               s.operator_class,s.lifecycle_state,s.hold_type
        FROM memory_items m
        JOIN memory_operator_state s ON s.item_id=m.item_id
        WHERE {}
        ORDER BY COALESCE(m.last_used_at,m.created_at) DESC
        LIMIT %s
        """).format(pg_sql.SQL(" AND ".join(clauses)))
        with self._connection() as conn:
            rows = conn.execute(sql_query, tuple(params)).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in ("occurred_at", "observed_at", "valid_from", "valid_to", "created_at", "last_used_at"):
                if item.get(key) is not None:
                    item[key] = item[key].isoformat()
            applications = int(item.get("application_count") or 0)
            successes = int(item.get("success_count") or 0)
            item["success_rate"] = round(successes * 100 / applications, 2) if applications else None
            result.append(item)
        return result

    def summary(self) -> dict[str, Any]:
        with self._connection() as conn:
            totals = conn.execute("SELECT count(*) AS total, count(*) FILTER (WHERE category='PROCEDURE') AS learned FROM memory_items").fetchone()
            states = conn.execute("SELECT operator_class,count(*) AS n FROM memory_operator_state GROUP BY operator_class").fetchall()
            usage = conn.execute("SELECT COALESCE(sum(retrieval_count),0) AS retrievals,COALESCE(sum(application_count),0) AS applications,COALESCE(sum(success_count),0) AS successes,COALESCE(sum(failure_count),0) AS failures FROM memory_items").fetchone()
            conflict_rows = conn.execute("SELECT count(*) AS n FROM retrieval_traces WHERE jsonb_array_length(conflicts)>0").fetchone()
            audit = conn.execute("SELECT count(*) AS n FROM audit_events").fetchone()
            derived = conn.execute("SELECT count(*) AS total,count(*) FILTER(WHERE status='READY') AS ready,count(*) FILTER(WHERE status='STALE') AS stale,count(*) FILTER(WHERE status='INVALID') AS invalid FROM memory_derived_artifacts").fetchone()
        applications = int(usage["applications"] or 0)
        successes = int(usage["successes"] or 0)
        return {
            "health": "OK",
            "memories_total": int(totals["total"] or 0),
            "learning_items": int(totals["learned"] or 0),
            "operator_classes": {str(r["operator_class"]): int(r["n"]) for r in states},
            "retrievals": int(usage["retrievals"] or 0),
            "applications": applications,
            "successes": successes,
            "failures": int(usage["failures"] or 0),
            "reuse_success_rate": round(successes * 100 / applications, 2) if applications else None,
            "conflicts": int(conflict_rows["n"] or 0),
            "audit_events": int(audit["n"] or 0),
            "derived_artifacts": {"total":int(derived["total"] or 0),"ready":int(derived["ready"] or 0),"stale":int(derived["stale"] or 0),"invalid":int(derived["invalid"] or 0)},
            "purge_direct_enabled": False,
        }

    def memory_candidates(self, query: str, namespaces: list[str], limit: int = 20, *, mission_id: str | None = None, session_id: str | None = None, valid_at: datetime | None = None, known_at: datetime | None = None) -> list[dict[str, Any]]:
        valid_moment = normalize_as_of(valid_at, "valid_at")
        known_moment = normalize_as_of(known_at, "known_at")
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT m.item_id,m.namespace,m.memory_key,m.category,m.content_json,m.content_text,m.provenance,m.confidence,
                       m.source,m.source_version,m.tags,m.occurred_at,m.observed_at,m.valid_from,m.valid_to,m.created_at,m.content_sha256,m.memory_scope,m.memory_scope_ref,
                       s.operator_class,s.lifecycle_state,s.hold_type,
                       ts_rank_cd(m.search_vector,plainto_tsquery('simple',%s)) AS text_rank,
                       (m.memory_key ILIKE %s OR m.content_text ILIKE %s) AS exact_substring_match
                FROM memory_items m
                JOIN memory_operator_state s ON s.item_id=m.item_id
                WHERE m.namespace=ANY(%s)
                  AND memory_scope_matches_context(m.memory_scope,m.memory_scope_ref,%s,%s,%s)
                  AND s.lifecycle_state <> 'PURGED'
                  AND memory_bitemporal_visible(m.valid_from,m.valid_to,m.observed_at,m.created_at,%s,%s)
                  AND (m.search_vector @@ plainto_tsquery('simple',%s) OR m.memory_key ILIKE %s OR m.content_text ILIKE %s)
                ORDER BY exact_substring_match DESC,text_rank DESC,m.confidence DESC,m.created_at DESC
                LIMIT %s
                """,
                (query, f"%{query}%", f"%{query}%", namespaces, self.access.project_id or "", mission_id or "", session_id or "", valid_moment, known_moment, query, f"%{query}%", f"%{query}%", min(max(int(limit), 1), 500)),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in ("occurred_at", "observed_at", "valid_from", "valid_to", "created_at"):
                if item.get(key) is not None:
                    item[key] = item[key].isoformat()
            result.append(item)
        return result

    def embedding_jobs(self, model_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT m.item_id,m.content_text,m.content_sha256
                FROM memory_items m
                LEFT JOIN memory_embeddings e ON e.item_id=m.item_id
                WHERE memory_bitemporal_visible(m.valid_from,m.valid_to,m.observed_at,m.created_at,now(),now())
                  AND (e.item_id IS NULL OR e.model_id<>%s OR e.content_sha256<>m.content_sha256 OR e.status<>'READY')
                ORDER BY m.created_at
                LIMIT %s
                """,
                (model_id, min(max(int(limit), 1), 1000)),
            ).fetchall()
        return [dict(row) for row in rows]

    def store_embedding(
        self,
        item_id: str,
        *,
        model_id: str,
        dimensions: int,
        embedding: list[float],
        content_sha256: str,
    ) -> None:
        require_canonical_mutation('embedding.store')
        if int(dimensions) != len(embedding):
            raise ValueError("embedding dimension mismatch")
        with self._connection() as conn:
            current = conn.execute(
                "SELECT content_sha256 FROM memory_items WHERE item_id=%s", (item_id,)
            ).fetchone()
            if not current:
                raise KeyError(item_id)
            if str(current["content_sha256"]) != content_sha256:
                raise ValueError("content changed before embedding commit")
            has_vector = conn.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='memory_embeddings' AND column_name='embedding_vector'"
            ).fetchone()
            if has_vector and int(dimensions) == 384:
                vector_literal = self._vector_literal(embedding)
                conn.execute(
                    """
                    INSERT INTO memory_embeddings(item_id,model_id,dimensions,embedding,embedding_vector,content_sha256,status,error_type,error_message,updated_at)
                    VALUES(%s,%s,%s,%s,%s::vector,%s,'READY',NULL,NULL,now())
                    ON CONFLICT(item_id) DO UPDATE SET
                      model_id=EXCLUDED.model_id,dimensions=EXCLUDED.dimensions,embedding=EXCLUDED.embedding,embedding_vector=EXCLUDED.embedding_vector,
                      content_sha256=EXCLUDED.content_sha256,status='READY',error_type=NULL,error_message=NULL,updated_at=now()
                    """,
                    (item_id, model_id, int(dimensions), embedding, vector_literal, content_sha256),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO memory_embeddings(item_id,model_id,dimensions,embedding,content_sha256,status,error_type,error_message,updated_at)
                    VALUES(%s,%s,%s,%s,%s,'READY',NULL,NULL,now())
                    ON CONFLICT(item_id) DO UPDATE SET
                      model_id=EXCLUDED.model_id,dimensions=EXCLUDED.dimensions,embedding=EXCLUDED.embedding,
                      content_sha256=EXCLUDED.content_sha256,status='READY',error_type=NULL,error_message=NULL,updated_at=now()
                    """,
                    (item_id, model_id, int(dimensions), embedding, content_sha256),
                )
            self._register_derived_artifact_in_conn(
                conn, artifact_type="EMBEDDING", artifact_ref=f"{item_id}:{model_id}",
                artifact_sha256=sha256_json({"model_id":model_id,"dimensions":int(dimensions),"embedding":embedding}),
                sources=[{"item_id":item_id,"content_sha256":content_sha256}],
                metadata={"model_id":model_id,"dimensions":int(dimensions)},
            )

    def mark_embedding_failed(
        self, item_id: str, *, model_id: str, content_sha256: str, error_type: str, error_message: str
    ) -> None:
        require_canonical_mutation('embedding.failed')
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_embeddings(item_id,model_id,dimensions,embedding,content_sha256,status,error_type,error_message,updated_at)
                VALUES(%s,%s,1,NULL,%s,'FAILED',%s,%s,now())
                ON CONFLICT(item_id) DO UPDATE SET
                  model_id=EXCLUDED.model_id,embedding=NULL,content_sha256=EXCLUDED.content_sha256,
                  status='FAILED',error_type=EXCLUDED.error_type,error_message=EXCLUDED.error_message,updated_at=now()
                """,
                (item_id, model_id, content_sha256, error_type[:160], error_message[:1000]),
            )

    @staticmethod
    def _vector_literal(values: list[float]) -> str:
        return "[" + ",".join(format(float(v), ".9g") for v in values) + "]"

    def semantic_search_pgvector(
        self,
        namespaces: list[str],
        model_id: str,
        query_embedding: list[float],
        *,
        limit: int = 100,
        mission_id: str | None = None,
        session_id: str | None = None,
        valid_at: datetime | None = None,
        known_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        if not query_embedding:
            return []
        vector_literal = self._vector_literal(query_embedding)
        valid_moment = normalize_as_of(valid_at, "valid_at")
        known_moment = normalize_as_of(known_at, "known_at")
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT m.item_id,m.namespace,m.memory_key,m.category,m.content_json,m.content_text,m.provenance,m.confidence,
                       m.source,m.source_version,m.tags,m.occurred_at,m.observed_at,m.valid_from,m.valid_to,m.created_at,m.content_sha256,m.memory_scope,m.memory_scope_ref,
                       s.operator_class,s.lifecycle_state,s.hold_type,
                       e.model_id,e.dimensions,
                       1 - (e.embedding_vector <=> %s::vector) AS semantic_similarity
                FROM memory_items m
                JOIN memory_operator_state s ON s.item_id=m.item_id
                JOIN memory_embeddings e ON e.item_id=m.item_id
                WHERE m.namespace=ANY(%s)
                  AND memory_scope_matches_context(m.memory_scope,m.memory_scope_ref,%s,%s,%s)
                  AND e.model_id=%s AND e.status='READY' AND e.content_sha256=m.content_sha256
                  AND e.embedding_vector IS NOT NULL
                  AND s.lifecycle_state NOT IN ('PURGED','QUARANTINED')
                  AND memory_bitemporal_visible(m.valid_from,m.valid_to,m.observed_at,m.created_at,%s,%s)
                ORDER BY e.embedding_vector <=> %s::vector
                LIMIT %s
                """,
                (vector_literal, namespaces, self.access.project_id or "", mission_id or "", session_id or "", model_id, valid_moment, known_moment, vector_literal, min(max(int(limit), 1), 1000)),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in ("occurred_at", "observed_at", "valid_from", "valid_to", "created_at"):
                if item.get(key) is not None:
                    item[key] = item[key].isoformat()
            item["semantic_similarity"] = float(item.get("semantic_similarity") or 0.0)
            item["retrieval_source"] = "SEMANTIC_PGVECTOR"
            result.append(item)
        return result

    def semantic_candidates(self, namespaces: list[str], model_id: str, *, limit: int = 1000, mission_id: str | None = None, session_id: str | None = None, valid_at: datetime | None = None, known_at: datetime | None = None) -> list[dict[str, Any]]:
        valid_moment = normalize_as_of(valid_at, "valid_at")
        known_moment = normalize_as_of(known_at, "known_at")
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT m.item_id,m.namespace,m.memory_key,m.category,m.content_json,m.content_text,m.provenance,m.confidence,
                       m.source,m.source_version,m.tags,m.occurred_at,m.observed_at,m.valid_from,m.valid_to,m.created_at,m.content_sha256,m.memory_scope,m.memory_scope_ref,
                       s.operator_class,s.lifecycle_state,s.hold_type,
                       e.model_id,e.dimensions,e.embedding
                FROM memory_items m
                JOIN memory_operator_state s ON s.item_id=m.item_id
                JOIN memory_embeddings e ON e.item_id=m.item_id
                WHERE m.namespace=ANY(%s)
                  AND memory_scope_matches_context(m.memory_scope,m.memory_scope_ref,%s,%s,%s)
                  AND e.model_id=%s AND e.status='READY' AND e.content_sha256=m.content_sha256
                  AND s.lifecycle_state NOT IN ('PURGED','QUARANTINED')
                  AND memory_bitemporal_visible(m.valid_from,m.valid_to,m.observed_at,m.created_at,%s,%s)
                ORDER BY COALESCE(m.last_used_at,m.observed_at) DESC
                LIMIT %s
                """,
                (namespaces, self.access.project_id or "", mission_id or "", session_id or "", model_id, valid_moment, known_moment, min(max(int(limit), 1), 5000)),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in ("occurred_at", "observed_at", "valid_from", "valid_to", "created_at"):
                if item.get(key) is not None:
                    item[key] = item[key].isoformat()
            result.append(item)
        return result

    def save_checkpoint(
        self,
        *,
        namespace: str,
        mission_id: str,
        step_index: int,
        state: dict[str, Any],
        checkpoint_id: str | None = None,
        migration_source: str | None = None,
        project_id: str | None = None,
        occurred_at: datetime | None = None,
        observed_at: datetime | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> dict[str, Any]:
        require_canonical_mutation('checkpoint.save')
        checkpoint_id = checkpoint_id or f"cp-{uuid.uuid4().hex}"
        state_hash = sha256_json(state)
        temporal = normalize_temporal_envelope(occurred_at=occurred_at, observed_at=observed_at, valid_from=valid_from, valid_to=valid_to)
        created_at = datetime.now(UTC)
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO checkpoints(checkpoint_id,namespace,mission_id,step_index,state_json,state_sha256,created_at,migration_source,project_id,occurred_at,observed_at,valid_from,valid_to) VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s)",
                (checkpoint_id, namespace, mission_id, int(step_index), canonical(state), state_hash, created_at, migration_source, project_id, temporal.occurred_at, temporal.observed_at, temporal.valid_from, temporal.valid_to),
            )
            self._audit(conn, "CHECKPOINT_SAVED", checkpoint_id, {"mission_id": mission_id, "step_index": int(step_index), "state_sha256": state_hash})
            required=[str(x) for x in (state.get("required_memory_ids") or []) if str(x)]
            if required:
                self._register_derived_artifact_in_conn(
                    conn,artifact_type="CHECKPOINT",artifact_ref=checkpoint_id,artifact_sha256=state_hash,
                    sources=required,metadata={"mission_id":mission_id,"step_index":int(step_index)},
                )
        return {
            "checkpoint_id": checkpoint_id, "namespace": namespace, "mission_id": mission_id, "project_id": project_id,
            "step_index": int(step_index), "state": state, "state_sha256": state_hash,
            "created_at": created_at.isoformat(), **temporal.as_dict(),
        }

    def latest_checkpoint(
        self,
        mission_id: str,
        namespaces: list[str] | None = None,
        *,
        project_id: str | None = None,
        valid_at: datetime | None = None,
        known_at: datetime | None = None,
    ) -> dict[str, Any] | None:
        valid_moment = normalize_as_of(valid_at, "valid_at")
        known_moment = normalize_as_of(known_at, "known_at")
        clauses = ["mission_id=%s", "memory_bitemporal_visible(valid_from,valid_to,observed_at,created_at,%s,%s)"]
        params: list[Any] = [mission_id, valid_moment, known_moment]
        if namespaces:
            clauses.append("namespace=ANY(%s)")
            params.append(namespaces)
        if project_id is not None:
            clauses.append("project_id=%s")
            params.append(project_id)
        with self._connection() as conn:
            row = conn.execute(
                # Dynamic SQL fragments below are fixed internal literals; caller values remain psycopg parameters.
                f"SELECT checkpoint_id,namespace,mission_id,step_index,state_json,state_sha256,occurred_at,observed_at,valid_from,valid_to,created_at,migration_source,project_id FROM checkpoints WHERE {' AND '.join(clauses)} ORDER BY step_index DESC,observed_at DESC LIMIT 1",  # nosec B608
                tuple(params),
            ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["state"] = value.pop("state_json")
        for key in ("occurred_at","observed_at","valid_from","valid_to","created_at"):
            if value.get(key) is not None:
                value[key] = value[key].isoformat()
        return value

    def record_retrieval_trace(
        self,
        query: str,
        namespaces: list[str],
        candidates: list[dict[str, Any]],
        selected: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
        *,
        state: dict[str, Any] | None = None,
        retrieval_modes: list[str] | None = None,
    ) -> str:
        require_canonical_mutation('retrieval.trace')
        trace_id = f"trace-{uuid.uuid4().hex}"
        clean = lambda rows: [{k: v for k, v in r.items() if k not in {"embedding"}} for r in rows]
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO retrieval_traces(trace_id,query_text,namespaces,candidates,selected,conflicts,state_json,retrieval_modes) VALUES(%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s)",
                (trace_id, query, namespaces, canonical(clean(candidates)), canonical(clean(selected)), canonical(conflicts), canonical(state) if state is not None else None, retrieval_modes or []),
            )
            if selected:
                ids = [str(item["item_id"]) for item in selected]
                conn.execute("UPDATE memory_items SET retrieval_count=retrieval_count+1,last_used_at=now() WHERE item_id=ANY(%s)", (ids,))
            self._audit(conn, "RETRIEVAL_TRACE_RECORDED", trace_id, {"query_sha256": hashlib.sha256(query.encode('utf-8')).hexdigest(), "candidate_count": len(candidates), "selected_count": len(selected), "conflict_count": len(conflicts)})
            source_refs=[{"item_id":str(x.get("item_id") or ""),"content_sha256":str(x.get("content_sha256") or "")} for x in selected if x.get("item_id") and x.get("content_sha256")]
            if source_refs:
                self._register_derived_artifact_in_conn(
                    conn,artifact_type="RETRIEVAL_TRACE",artifact_ref=trace_id,
                    artifact_sha256=sha256_json({"query":query,"selected":clean(selected),"modes":retrieval_modes or []}),
                    sources=source_refs,metadata={"retrieval_modes":retrieval_modes or [],"selected_count":len(selected)},
                )
        return trace_id


    def latest_retrieval_trace(self) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT trace_id,query_text,namespaces,candidates,selected,conflicts,state_json,retrieval_modes,created_at
                FROM retrieval_traces
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        out = dict(row)
        if out.get("created_at") is not None:
            out["created_at"] = out["created_at"].isoformat()
        out["candidate_count"] = len(out.get("candidates") or [])
        out["selected_count"] = len(out.get("selected") or [])
        out["conflict_count"] = len(out.get("conflicts") or [])
        return out

    def v52_observability(self) -> dict[str, Any]:
        with self._connection() as conn:
            traces = conn.execute("SELECT count(*) AS n FROM retrieval_traces").fetchone()
            latest_trace = conn.execute("SELECT trace_id,retrieval_modes,created_at FROM retrieval_traces ORDER BY created_at DESC LIMIT 1").fetchone()
            quality = conn.execute("SELECT run_id,gate,candidate_ref,metrics,created_at FROM retrieval_quality_runs ORDER BY created_at DESC LIMIT 1").fetchone()
            capacity = conn.execute("SELECT snapshot_id,state,reasons,metrics,created_at FROM memory_capacity_snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
            evolution = conn.execute("SELECT proof_id,status,candidate_ref,migration_version,created_at FROM memory_evolution_proofs ORDER BY created_at DESC LIMIT 1").fetchone()
            rls = conn.execute(
                """
                SELECT relname,relrowsecurity,relforcerowsecurity
                FROM pg_class
                WHERE relname = ANY(%s)
                ORDER BY relname
                """,
                (["retrieval_quality_golden_sets","retrieval_quality_runs","memory_capacity_snapshots","memory_evolution_proofs"],),
            ).fetchall()
        def iso(row: Any) -> dict[str, Any] | None:
            if row is None:
                return None
            value = dict(row)
            if value.get("created_at") is not None:
                value["created_at"] = value["created_at"].isoformat()
            return value
        return {
            "contract": "V5.2_OBSERVABILITY_LOCAL_V1",
            "fallback": "SIGNED_API_METRICS_PLUS_RETRIEVAL_TRACES",
            "phoenix_parallel": "OPTIONAL_NOT_REQUIRED_FOR_RC1_PROMOTION_ON_THIS_HOST",
            "retrieval_traces_total": int(traces["n"] or 0),
            "latest_trace": iso(latest_trace),
            "latest_retrieval_quality_run": iso(quality),
            "latest_capacity_snapshot": iso(capacity),
            "latest_evolution_proof": iso(evolution),
            "rls": {str(row["relname"]): {"enabled": bool(row["relrowsecurity"]), "forced": bool(row["relforcerowsecurity"])} for row in rls},
            "status": "PASS",
        }

    def acquire_lease(self, lease_key: str, *, ttl_seconds: int = 30) -> dict[str, Any]:
        require_canonical_mutation('lease.acquire')
        agent_id = self.access.agent_id
        if not agent_id or agent_id == "__SYSTEM__":
            raise PermissionError("agent identity required for lease")
        if not lease_key or len(lease_key) > 240:
            raise ValueError("invalid lease_key")
        ttl = min(max(int(ttl_seconds), 1), 3600)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT tenant_id,lease_key,owner_agent_id,lease_version,fencing_token,expires_at FROM agent_leases WHERE tenant_id=%s AND lease_key=%s FOR UPDATE",
                (self.tenant_id, lease_key),
            ).fetchone()
            now = datetime.now(UTC)
            if row and row["expires_at"] > now and str(row["owner_agent_id"]) != agent_id:
                raise ConcurrencyConflict(f"lease held by another agent: {lease_key}")
            version = int(row["lease_version"] if row else 0) + 1
            token = int(row["fencing_token"] if row else 0) + 1
            expires = now + timedelta(seconds=ttl)
            updated = conn.execute(
                """INSERT INTO agent_leases(tenant_id,lease_key,owner_agent_id,lease_version,fencing_token,expires_at,updated_at)
                   VALUES(%s,%s,%s,%s,%s,%s,now())
                   ON CONFLICT(tenant_id,lease_key) DO UPDATE SET
                     owner_agent_id=EXCLUDED.owner_agent_id,lease_version=EXCLUDED.lease_version,
                     fencing_token=EXCLUDED.fencing_token,expires_at=EXCLUDED.expires_at,updated_at=now()
                   RETURNING tenant_id,lease_key,owner_agent_id,lease_version,fencing_token,expires_at,updated_at""",
                (self.tenant_id, lease_key, agent_id, version, token, expires),
            ).fetchone()
            self._audit(conn, "AGENT_LEASE_ACQUIRED", lease_key, {"agent_id": agent_id, "lease_version": version, "fencing_token": token, "ttl_seconds": ttl})
        result = dict(updated)
        for key in ("expires_at", "updated_at"):
            result[key] = result[key].isoformat()
        return result

    def release_lease(self, lease_key: str, *, fencing_token: int) -> dict[str, Any]:
        require_canonical_mutation('lease.release')
        agent_id = self.access.agent_id
        if not agent_id or agent_id == "__SYSTEM__":
            raise PermissionError("agent identity required for lease")
        with self._connection() as conn:
            row = conn.execute(
                "SELECT owner_agent_id,fencing_token FROM agent_leases WHERE tenant_id=%s AND lease_key=%s FOR UPDATE",
                (self.tenant_id, lease_key),
            ).fetchone()
            if not row:
                raise KeyError(lease_key)
            if str(row["owner_agent_id"]) != agent_id or int(row["fencing_token"]) != int(fencing_token):
                raise ConcurrencyConflict("stale or foreign fencing token")
            updated = conn.execute(
                "UPDATE agent_leases SET expires_at=now(),updated_at=now() WHERE tenant_id=%s AND lease_key=%s RETURNING lease_key,owner_agent_id,lease_version,fencing_token,expires_at,updated_at",
                (self.tenant_id, lease_key),
            ).fetchone()
            self._audit(conn, "AGENT_LEASE_RELEASED", lease_key, {"agent_id": agent_id, "fencing_token": int(fencing_token)})
        result = dict(updated)
        for key in ("expires_at", "updated_at"):
            result[key] = result[key].isoformat()
        return result

    @staticmethod
    def _audit_row_digest(row: Any) -> str:
        ts = row["created_at"].astimezone(UTC).isoformat()
        return hashlib.sha256(
            (str(row["previous_hash"]) + canonical(row["payload"]) + str(row["event_type"]) + ts).encode()
        ).hexdigest()

    @staticmethod
    def _audit_manifest_root(rows: list[Any]) -> str:
        material = "\n".join(
            f"{int(row['seq'])}:{row['previous_hash']}:{row['event_hash']}" for row in rows
        )
        return hashlib.sha256(material.encode()).hexdigest()

    @classmethod
    def _audit_dag_assessment(cls, rows: list[Any]) -> dict[str, Any]:
        seen = {"0" * 64}
        invalid_hash: list[int] = []
        missing_parent: list[int] = []
        children: dict[str, list[int]] = {}
        for row in rows:
            seq = int(row["seq"])
            previous_hash = str(row["previous_hash"])
            event_hash = str(row["event_hash"])
            if cls._audit_row_digest(row) != event_hash:
                invalid_hash.append(seq)
            if previous_hash not in seen:
                missing_parent.append(seq)
            children.setdefault(previous_hash, []).append(seq)
            seen.add(event_hash)
        fork_groups = [seqs for parent, seqs in children.items() if len(seqs) > 1]
        return {
            "invalid_hash": invalid_hash,
            "missing_parent": missing_parent,
            "fork_groups": fork_groups,
            "fork_group_count": len(fork_groups),
            "fork_event_count": sum(len(group) for group in fork_groups),
        }

    def reseal_audit_chain(self, *, reason: str = "CONCURRENCY_FORK_REPAIR") -> dict[str, Any]:
        require_canonical_mutation('audit.reseal')
        with self._connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('memory.audit.chain'))")
            rows = conn.execute(
                "SELECT seq,event_type,target_id,payload,previous_hash,event_hash,created_at FROM audit_events ORDER BY seq"
            ).fetchall()
            if not rows:
                return {"resealed": False, "reason": "EMPTY_AUDIT_CHAIN", "events": 0}
            assessment = self._audit_dag_assessment(rows)
            if assessment["invalid_hash"] or assessment["missing_parent"]:
                raise RuntimeError("audit history contains invalid hashes or missing parents; reseal refused")
            manifest_root = self._audit_manifest_root(rows)
            sealed_until_seq = int(rows[-1]["seq"])
            payload = {
                "algorithm": "SHA256-AUDIT-DAG-MANIFEST-V1",
                "reason": str(reason),
                "sealed_until_seq": sealed_until_seq,
                "manifest_root": manifest_root,
                "legacy_fork_groups": assessment["fork_groups"],
                "legacy_fork_group_count": assessment["fork_group_count"],
                "legacy_fork_event_count": assessment["fork_event_count"],
                "invalid_hash_count": 0,
                "missing_parent_count": 0,
            }
            event_hash = self._audit(conn, "AUDIT_CHAIN_RESEALED", "audit_events", payload)
            seal = conn.execute(
                "SELECT seq,created_at,event_hash FROM audit_events WHERE event_hash=%s ORDER BY seq DESC LIMIT 1",
                (event_hash,),
            ).fetchone()
        return {
            "resealed": True,
            "seal_seq": int(seal["seq"]),
            "sealed_until_seq": sealed_until_seq,
            "manifest_root": manifest_root,
            "legacy_fork_group_count": assessment["fork_group_count"],
            "legacy_fork_event_count": assessment["fork_event_count"],
            "seal_event_hash": str(seal["event_hash"]),
            "sealed_at": seal["created_at"].astimezone(UTC).isoformat(),
        }

    def verify_audit_chain(self) -> dict[str, Any]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT seq,event_type,target_id,payload,previous_hash,event_hash,created_at FROM audit_events ORDER BY seq"
            ).fetchall()
        if not rows:
            return {"ok": True, "errors": [], "events": 0, "head": "0" * 64, "resealed": False}

        seal_rows = [
            row for row in rows
            if str(row["event_type"]) == "AUDIT_CHAIN_RESEALED"
            and isinstance(row["payload"], dict)
            and row["payload"].get("algorithm") == "SHA256-AUDIT-DAG-MANIFEST-V1"
        ]
        if not seal_rows:
            previous = "0" * 64
            errors: list[int] = []
            for row in rows:
                ts = row["created_at"].astimezone(UTC).isoformat()
                expected = hashlib.sha256(
                    (previous + canonical(row["payload"]) + str(row["event_type"]) + ts).encode()
                ).hexdigest()
                if str(row["previous_hash"]) != previous or str(row["event_hash"]) != expected:
                    errors.append(int(row["seq"]))
                previous = str(row["event_hash"])
            return {"ok": not errors, "errors": errors, "events": len(rows), "head": previous, "resealed": False}

        seal = seal_rows[-1]
        payload = dict(seal["payload"])
        sealed_until_seq = int(payload.get("sealed_until_seq", -1))
        legacy_rows = [row for row in rows if int(row["seq"]) <= sealed_until_seq]
        active_rows = [row for row in rows if int(row["seq"]) > sealed_until_seq]
        legacy = self._audit_dag_assessment(legacy_rows)
        manifest_root = self._audit_manifest_root(legacy_rows)
        manifest_ok = hmac.compare_digest(manifest_root, str(payload.get("manifest_root") or ""))

        previous = str(legacy_rows[-1]["event_hash"]) if legacy_rows else "0" * 64
        strict_errors: list[int] = []
        for row in active_rows:
            ts = row["created_at"].astimezone(UTC).isoformat()
            expected = hashlib.sha256(
                (previous + canonical(row["payload"]) + str(row["event_type"]) + ts).encode()
            ).hexdigest()
            if str(row["previous_hash"]) != previous or str(row["event_hash"]) != expected:
                strict_errors.append(int(row["seq"]))
            previous = str(row["event_hash"])

        errors = sorted(set(legacy["invalid_hash"] + legacy["missing_parent"] + strict_errors))
        if not manifest_ok:
            errors.append(int(seal["seq"]))
        ok = not errors
        return {
            "ok": ok,
            "errors": errors,
            "events": len(rows),
            "head": previous,
            "resealed": True,
            "reseal_seq": int(seal["seq"]),
            "sealed_until_seq": sealed_until_seq,
            "legacy_manifest_root": manifest_root,
            "legacy_manifest_matches_seal": manifest_ok,
            "legacy_fork_group_count": legacy["fork_group_count"],
            "legacy_fork_event_count": legacy["fork_event_count"],
            "legacy_invalid_hash": legacy["invalid_hash"],
            "legacy_missing_parent": legacy["missing_parent"],
            "strict_chain_from_seq": int(seal["seq"]),
            "strict_errors": strict_errors,
        }

    def create_retrieval_golden_set(self, *, name: str, version: int, cases: list[dict[str, Any]], created_by: str) -> dict[str, Any]:
        require_canonical_mutation('retrieval.quality.golden.create')
        clean_name = str(name or '').strip()
        if not clean_name or len(clean_name) > 160:
            raise ValueError('invalid golden set name')
        if int(version) < 1 or not cases:
            raise ValueError('golden set requires positive version and cases')
        normalized=[]
        seen=set()
        for raw in cases:
            case_id=str(raw.get('case_id') or '').strip()
            query=str(raw.get('query') or '').strip()
            namespaces=[str(x).strip().upper() for x in raw.get('namespaces',[]) if str(x).strip()]
            expected=sorted({str(x) for x in raw.get('expected_item_ids',[]) if str(x)})
            forbidden=sorted({str(x) for x in raw.get('forbidden_item_ids',[]) if str(x)})
            temporal_forbidden=sorted({str(x) for x in raw.get('temporal_forbidden_item_ids',[]) if str(x)})
            allowed_authorities=sorted({str(x).upper() for x in raw.get('allowed_authorities',[]) if str(x)})
            if not case_id or case_id in seen or not query or not namespaces:
                raise ValueError('invalid retrieval golden case')
            if set(expected) & (set(forbidden) | set(temporal_forbidden)):
                raise ValueError('expected items cannot be forbidden')
            seen.add(case_id)
            normalized.append({
                'case_id':case_id,'query':query,'namespaces':namespaces,'expected_item_ids':expected,
                'forbidden_item_ids':forbidden,'temporal_forbidden_item_ids':temporal_forbidden,
                'allowed_scopes':list(raw.get('allowed_scopes') or []),'allowed_authorities':allowed_authorities,
                'mission_id':raw.get('mission_id'),'session_id':raw.get('session_id'),
                'valid_at':raw.get('valid_at'),'known_at':raw.get('known_at'),'limit':int(raw.get('limit') or 8),
                'metadata':dict(raw.get('metadata') or {}),
            })
        definition={'name':clean_name,'version':int(version),'cases':normalized}
        definition_sha=sha256_json(definition)
        golden_set_id=f"rqs-{uuid.uuid4().hex}"
        with self._connection() as conn:
            conn.execute(
                """INSERT INTO retrieval_quality_golden_sets(golden_set_id,tenant_id,name,version,definition,definition_sha256,status,created_by)
                   VALUES(%s,%s,%s,%s,%s::jsonb,%s,'ACTIVE',%s)""",
                (golden_set_id,self.tenant_id,clean_name,int(version),canonical(definition),definition_sha,created_by),
            )
            self._audit(conn,'RETRIEVAL_QUALITY_GOLDEN_CREATED',golden_set_id,{'name':clean_name,'version':int(version),'definition_sha256':definition_sha,'case_count':len(normalized)})
        return {'golden_set_id':golden_set_id,'name':clean_name,'version':int(version),'definition_sha256':definition_sha,'case_count':len(normalized),'status':'ACTIVE'}

    def get_retrieval_golden_set(self, golden_set_id: str) -> dict[str, Any]:
        with self._connection() as conn:
            row=conn.execute(
                "SELECT golden_set_id,name,version,definition,definition_sha256,status,created_by,created_at FROM retrieval_quality_golden_sets WHERE tenant_id=%s AND golden_set_id=%s",
                (self.tenant_id,golden_set_id),
            ).fetchone()
        if not row:
            raise KeyError(golden_set_id)
        result=dict(row)
        definition=dict(result.pop('definition') or {})
        result['cases']=list(definition.get('cases') or [])
        result['created_at']=result['created_at'].isoformat()
        return result

    def record_retrieval_quality_run(self, *, golden_set_id: str, candidate_ref: str, baseline_ref: str | None, thresholds: dict[str, Any], metrics: dict[str, Any], status: str, reasons: list[str], case_results: list[dict[str, Any]], created_by: str) -> dict[str, Any]:
        require_canonical_mutation('retrieval.quality.run')
        decision=str(status or '').upper()
        if decision not in {'PASS','DENY'}:
            raise ValueError('invalid retrieval quality status')
        run_id=f"rqr-{uuid.uuid4().hex}"
        evidence={'golden_set_id':golden_set_id,'candidate_ref':str(candidate_ref),'baseline_ref':baseline_ref,'thresholds':thresholds,'metrics':metrics,'status':decision,'reasons':reasons,'case_results':case_results}
        evidence_sha=sha256_json(evidence)
        persisted_metrics={'aggregate':metrics,'thresholds':thresholds,'baseline_ref':baseline_ref,'reasons':reasons,'case_results':case_results}
        with self._connection() as conn:
            exists=conn.execute("SELECT 1 FROM retrieval_quality_golden_sets WHERE tenant_id=%s AND golden_set_id=%s",(self.tenant_id,golden_set_id)).fetchone()
            if not exists:
                raise KeyError(golden_set_id)
            conn.execute(
                """INSERT INTO retrieval_quality_runs(run_id,tenant_id,golden_set_id,candidate_ref,metrics,gate,evidence_sha256,created_by)
                   VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s,%s)""",
                (run_id,self.tenant_id,golden_set_id,str(candidate_ref),canonical(persisted_metrics),decision,evidence_sha,created_by),
            )
            self._audit(conn,'RETRIEVAL_QUALITY_RUN_RECORDED',run_id,{'golden_set_id':golden_set_id,'candidate_ref':str(candidate_ref),'baseline_ref':baseline_ref,'status':decision,'evidence_sha256':evidence_sha})
        return {'run_id':run_id,'golden_set_id':golden_set_id,'status':decision,'metrics':metrics,'reasons':reasons,'case_count':len(case_results),'evidence_sha256':evidence_sha}

    def list_retrieval_quality_runs(self, golden_set_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows=conn.execute(
                "SELECT run_id,golden_set_id,candidate_ref,metrics,gate,evidence_sha256,created_by,created_at FROM retrieval_quality_runs WHERE tenant_id=%s AND golden_set_id=%s ORDER BY created_at DESC LIMIT %s",
                (self.tenant_id,golden_set_id,min(max(int(limit),1),500)),
            ).fetchall()
        result=[]
        for row in rows:
            value=dict(row); value['created_at']=value['created_at'].isoformat(); result.append(value)
        return result
    def record_capacity_snapshot(self, *, metrics: dict[str, Any], state: str, reasons: list[str], created_by: str) -> dict[str, Any]:
        require_canonical_mutation('capacity.snapshot')
        decision=str(state or '').upper()
        if decision not in {'NORMAL','WARN','PROTECT'}:
            raise ValueError('invalid capacity state')
        snapshot_id=f"cap-{uuid.uuid4().hex}"
        with self._connection() as conn:
            row=conn.execute("""INSERT INTO memory_capacity_snapshots(snapshot_id,tenant_id,metrics,state,reasons,created_by)
                VALUES(%s,%s,%s::jsonb,%s,%s::jsonb,%s) RETURNING snapshot_id,state,created_at""",
                (snapshot_id,self.tenant_id,canonical(metrics),decision,canonical(reasons),created_by)).fetchone()
            self._audit(conn,'MEMORY_CAPACITY_SNAPSHOT_RECORDED',snapshot_id,{'state':decision,'reasons':reasons})
        return {'snapshot_id':snapshot_id,'state':decision,'created_at':row['created_at'].isoformat()}

    def record_evolution_proof(self, *, migration_version: str, candidate_ref: str, proof: dict[str, Any], status: str, reasons: list[str], created_by: str) -> dict[str, Any]:
        require_canonical_mutation('evolution.proof')
        decision=str(status or '').upper()
        if decision not in {'PASS','DENY'}:
            raise ValueError('invalid evolution proof status')
        proof_id=f"evo-{uuid.uuid4().hex}"
        digest=sha256_json({'migration_version':migration_version,'candidate_ref':candidate_ref,'proof':proof,'status':decision,'reasons':reasons})
        with self._connection() as conn:
            row=conn.execute("""INSERT INTO memory_evolution_proofs(proof_id,tenant_id,migration_version,candidate_ref,proof,status,reasons,evidence_sha256,created_by)
                VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s) RETURNING proof_id,status,evidence_sha256,created_at""",
                (proof_id,self.tenant_id,str(migration_version),str(candidate_ref),canonical(proof),decision,canonical(reasons),digest,created_by)).fetchone()
            self._audit(conn,'MEMORY_EVOLUTION_PROOF_RECORDED',proof_id,{'migration_version':migration_version,'candidate_ref':candidate_ref,'status':decision,'evidence_sha256':digest})
        return {'proof_id':proof_id,'status':decision,'evidence_sha256':digest,'created_at':row['created_at'].isoformat()}

    def record_ai_integration_suggestion(self, *, external_system_id: str, external_trace_id: str, suggestion_type: str, target_item_id: str | None, raw_payload: dict[str, Any], normalized_payload: dict[str, Any], risk_level: str, created_by: str) -> dict[str, Any]:
        require_canonical_mutation('ai.integration.suggestion.record')
        kind = str(suggestion_type or '').upper()
        if kind not in {'MEMORY_CREATE','MEMORY_REVISE','MEMORY_CLASSIFY','MEMORY_ARCHIVE','DUPLICATE_REVIEW','CONFLICT_REVIEW','SUMMARY'}:
            raise ValueError('invalid AI suggestion type')
        risk = str(risk_level or '').upper()
        if risk not in {'LOW','MEDIUM','HIGH','CRITICAL'}:
            raise ValueError('invalid AI suggestion risk')
        evidence = {'external_system_id': str(external_system_id), 'external_trace_id': str(external_trace_id), 'suggestion_type': kind, 'target_item_id': target_item_id, 'raw_payload': raw_payload, 'normalized_payload': normalized_payload, 'risk_level': risk}
        digest = sha256_json(evidence)
        suggestion_id = f"ais-{uuid.uuid4().hex}"
        with self._connection() as conn:
            row = conn.execute("""INSERT INTO ai_integration_suggestions(suggestion_id,tenant_id,external_system_id,external_trace_id,suggestion_type,target_item_id,raw_payload,normalized_payload,risk_level,evidence_sha256,created_by)
                   VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s)
                   ON CONFLICT(tenant_id,external_system_id,external_trace_id) DO NOTHING
                   RETURNING suggestion_id,external_system_id,external_trace_id,suggestion_type,risk_level,evidence_sha256,created_at""", (suggestion_id,self.tenant_id,str(external_system_id),str(external_trace_id),kind,target_item_id,canonical(raw_payload),canonical(normalized_payload),risk,digest,created_by)).fetchone()
            replayed = False
            if row is None:
                replayed = True
                row = conn.execute("""SELECT suggestion_id,external_system_id,external_trace_id,suggestion_type,risk_level,evidence_sha256,created_at FROM ai_integration_suggestions WHERE tenant_id=%s AND external_system_id=%s AND external_trace_id=%s""", (self.tenant_id,str(external_system_id),str(external_trace_id))).fetchone()
            else:
                self._audit(conn,'AI_INTEGRATION_SUGGESTION_RECORDED',suggestion_id,{'external_system_id':str(external_system_id),'external_trace_id':str(external_trace_id),'suggestion_type':kind,'risk_level':risk,'evidence_sha256':digest})
        result = dict(row); result['created_at'] = result['created_at'].isoformat(); result['contract'] = 'V5.3_AI_INTEGRATION_ADAPTER'; result['replayed'] = replayed
        return result

    def get_ai_integration_suggestion(self, suggestion_id: str) -> dict[str, Any]:
        with self._connection() as conn:
            row = conn.execute("""SELECT suggestion_id,external_system_id,external_trace_id,suggestion_type,target_item_id,raw_payload,normalized_payload,risk_level,evidence_sha256,created_by,created_at FROM ai_integration_suggestions WHERE tenant_id=%s AND suggestion_id=%s""", (self.tenant_id,str(suggestion_id))).fetchone()
        if not row:
            raise KeyError(suggestion_id)
        result = dict(row); result['created_at'] = result['created_at'].isoformat(); return result

    def latest_ai_integration_decision(self, suggestion_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("""SELECT decision_id,suggestion_id,decision,rationale,evidence,promoted_item_id,evidence_sha256,created_by,created_at FROM ai_integration_decisions WHERE tenant_id=%s AND suggestion_id=%s ORDER BY created_at DESC LIMIT 1""", (self.tenant_id,str(suggestion_id))).fetchone()
        if row is None:
            return None
        result = dict(row); result['created_at'] = result['created_at'].isoformat(); return result

    def list_ai_integration_suggestions(self, *, suggestion_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = min(max(int(limit), 1), 500)
        clauses = ["s.tenant_id=%s"]
        params: list[Any] = [self.tenant_id]
        if suggestion_type:
            clauses.append("s.suggestion_type=%s")
            params.append(str(suggestion_type).upper())
        params.append(limit)
        sql_query = pg_sql.SQL("""SELECT s.suggestion_id,s.external_system_id,s.external_trace_id,s.suggestion_type,s.target_item_id,s.normalized_payload,s.risk_level,s.evidence_sha256,s.created_by,s.created_at,
                   d.decision AS latest_decision,d.promoted_item_id AS latest_promoted_item_id,d.created_at AS latest_decision_at
            FROM ai_integration_suggestions s
            LEFT JOIN LATERAL (SELECT decision,promoted_item_id,created_at FROM ai_integration_decisions d WHERE d.tenant_id=s.tenant_id AND d.suggestion_id=s.suggestion_id ORDER BY d.created_at DESC LIMIT 1) d ON true
            WHERE {} ORDER BY s.created_at DESC LIMIT %s""").format(pg_sql.SQL(" AND ").join(pg_sql.SQL(clause) for clause in clauses))
        with self._connection() as conn:
            rows = conn.execute(sql_query, tuple(params)).fetchall()
        result=[]
        for row in rows:
            value=dict(row); value['created_at']=value['created_at'].isoformat()
            if value.get('latest_decision_at') is not None:
                value['latest_decision_at']=value['latest_decision_at'].isoformat()
            result.append(value)
        return result

    def record_ai_integration_decision(self, *, suggestion_id: str, decision: str, rationale: str, evidence: dict[str, Any], promoted_item_id: str | None, created_by: str) -> dict[str, Any]:
        require_canonical_mutation('ai.integration.decision.record')
        normalized = str(decision or '').upper()
        if normalized not in {'ACCEPTED','REJECTED','PROMOTED'}:
            raise ValueError('invalid AI integration decision')
        payload = {'suggestion_id': str(suggestion_id), 'decision': normalized, 'rationale': str(rationale or ''), 'evidence': evidence or {}, 'promoted_item_id': promoted_item_id}
        digest = sha256_json(payload); decision_id = f"aid-{uuid.uuid4().hex}"
        with self._connection() as conn:
            exists = conn.execute('SELECT 1 FROM ai_integration_suggestions WHERE tenant_id=%s AND suggestion_id=%s',(self.tenant_id,str(suggestion_id))).fetchone()
            if not exists:
                raise KeyError(suggestion_id)
            row = conn.execute("""INSERT INTO ai_integration_decisions(decision_id,tenant_id,suggestion_id,decision,rationale,evidence,promoted_item_id,evidence_sha256,created_by)
                   VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s) RETURNING decision_id,suggestion_id,decision,promoted_item_id,evidence_sha256,created_at""", (decision_id,self.tenant_id,str(suggestion_id),normalized,str(rationale or ''),canonical(evidence or {}),promoted_item_id,digest,created_by)).fetchone()
            self._audit(conn,'AI_INTEGRATION_DECISION_RECORDED',decision_id,{'suggestion_id':str(suggestion_id),'decision':normalized,'promoted_item_id':promoted_item_id,'evidence_sha256':digest})
        result=dict(row); result['created_at']=result['created_at'].isoformat(); result['contract']='V5.3_AI_INTEGRATION_ADAPTER'; return result
