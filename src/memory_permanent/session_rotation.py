from __future__ import annotations

import re
import uuid
from typing import Any

from .canonical_mutation import CanonicalMutationService, require_canonical_mutation
from .store import PostgresMemoryStore, canonical, sha256_json

SESSION_ROTATION_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS sovereign_sessions(
  session_id text PRIMARY KEY,
  identity_json jsonb NOT NULL,
  scope text NOT NULL,
  objective text NOT NULL,
  critical_rules jsonb NOT NULL DEFAULT '[]'::jsonb,
  operational_state jsonb NOT NULL DEFAULT '{}'::jsonb,
  last_confirmed_action text,
  blockers jsonb NOT NULL DEFAULT '[]'::jsonb,
  pending jsonb NOT NULL DEFAULT '[]'::jsonb,
  next_safe_action text,
  active_authorizations jsonb NOT NULL DEFAULT '[]'::jsonb,
  required_memory_ids text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS external_session_bindings(
  binding_id text PRIMARY KEY,
  session_id text NOT NULL REFERENCES sovereign_sessions(session_id) ON DELETE RESTRICT,
  provider text NOT NULL,
  external_session_ref text NOT NULL,
  canonical_external_ref text,
  external_project_ref text,
  status text NOT NULL CHECK(status IN ('CURRENT','PENDING_VALIDATION','VALIDATED','SUPERSEDED','ARCHIVED','ABORTED')),
  context_pack_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  validated_at timestamptz,
  superseded_at timestamptz,
  UNIQUE(provider, external_session_ref)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_session_current_binding ON external_session_bindings(session_id) WHERE status='CURRENT';
CREATE INDEX IF NOT EXISTS idx_bindings_session ON external_session_bindings(session_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_external_session_resolver ON external_session_bindings(lower(provider),canonical_external_ref,status,created_at DESC);
CREATE TABLE IF NOT EXISTS session_checkpoints(
  checkpoint_id text PRIMARY KEY,
  session_id text NOT NULL REFERENCES sovereign_sessions(session_id) ON DELETE RESTRICT,
  state_json jsonb NOT NULL,
  state_sha256 text NOT NULL,
  last_event_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_session_checkpoints_session ON session_checkpoints(session_id,created_at DESC);
CREATE TABLE IF NOT EXISTS context_packs(
  context_pack_id text PRIMARY KEY,
  session_id text NOT NULL REFERENCES sovereign_sessions(session_id) ON DELETE RESTRICT,
  checkpoint_id text NOT NULL REFERENCES session_checkpoints(checkpoint_id) ON DELETE RESTRICT,
  context_json jsonb NOT NULL,
  context_sha256 text NOT NULL,
  required_memory_ids text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_context_packs_session ON context_packs(session_id,created_at DESC);
CREATE TABLE IF NOT EXISTS session_rotations(
  rotation_id text PRIMARY KEY,
  session_id text NOT NULL REFERENCES sovereign_sessions(session_id) ON DELETE RESTRICT,
  old_binding_id text NOT NULL REFERENCES external_session_bindings(binding_id) ON DELETE RESTRICT,
  new_binding_id text REFERENCES external_session_bindings(binding_id) ON DELETE RESTRICT,
  checkpoint_id text REFERENCES session_checkpoints(checkpoint_id) ON DELETE RESTRICT,
  context_pack_id text REFERENCES context_packs(context_pack_id) ON DELETE RESTRICT,
  status text NOT NULL CHECK(status IN ('REQUESTED','WAITING_SAFE_POINT','CHECKPOINTED','NEW_BOUND','VALIDATED','COMPLETED','ABORTED')),
  reason text NOT NULL,
  safe_point_json jsonb NOT NULL,
  memory_before_mb double precision,
  memory_after_mb double precision,
  memory_released_mb double precision,
  client_close_evidence jsonb,
  failure_reason text,
  requested_at timestamptz NOT NULL DEFAULT now(),
  validated_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_session_rotations_session ON session_rotations(session_id,requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_session_rotations_status ON session_rotations(status,updated_at);
"""

_SAFE_POINT_REQUIRED = {
    "streaming_critical": False,
    "upload_unconfirmed": False,
    "non_idempotent_write_pending": False,
    "tool_call_unpersisted": False,
    "last_event_confirmed": True,
    "checkpoint_possible": True,
}


def safe_point_ready(value: dict[str, Any]) -> bool:
    return all(value.get(key) is expected for key, expected in _SAFE_POINT_REQUIRED.items())


def normalize_external_session_ref(provider: str, external_session_ref: str) -> dict[str, str | None]:
    provider_value = provider.strip()
    raw = external_session_ref.strip()
    if not provider_value or not raw:
        raise ValueError("provider and external_session_ref must be non-empty")
    canonical = raw
    project_ref: str | None = None
    if provider_value.casefold() in {"chatgpt", "chatgpt_web", "openai_chatgpt"}:
        match = re.search(r"(?:^|/)g/g-p-(?P<project>[^/]+)/c/(?P<conversation>[A-Za-z0-9-]+)", raw)
        if match:
            canonical = match.group("conversation")
            project_ref = f"g/g-p-{match.group('project')}"
        else:
            c_match = re.search(r"(?:^|/)c/(?P<conversation>[A-Za-z0-9-]+)", raw)
            if c_match:
                canonical = c_match.group("conversation")
    return {
        "provider": provider_value,
        "external_session_ref": raw,
        "canonical_external_ref": canonical,
        "external_project_ref": project_ref,
    }


def _normalize(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key, value in list(result.items()):
        if hasattr(value, "isoformat"):
            result[key] = value.isoformat()
    return result


class SessionRotationRepository:
    """Canonical Session Rotation state inside the sovereign Memory Core."""

    def __init__(self, store: PostgresMemoryStore, *, initialize: bool = True) -> None:
        self.store = store
        if initialize:
            with self.store.connection() as conn:
                conn.execute(SESSION_ROTATION_SCHEMA)

    def create_session(self, *, session_id: str, identity: dict[str, Any], scope: str, objective: str,
                       critical_rules: list[Any] | dict[str, Any], operational_state: dict[str, Any],
                       last_confirmed_action: str | None, blockers: list[Any], pending: list[Any],
                       next_safe_action: str | None, active_authorizations: list[Any],
                       required_memory_ids: list[str]) -> dict[str, Any]:
        require_canonical_mutation('session.create')
        payload = {
            "identity_json": identity, "scope": scope, "objective": objective,
            "critical_rules": critical_rules, "operational_state": operational_state,
            "last_confirmed_action": last_confirmed_action, "blockers": blockers, "pending": pending,
            "next_safe_action": next_safe_action, "active_authorizations": active_authorizations,
            "required_memory_ids": sorted(set(required_memory_ids)),
        }
        with self.store.connection() as conn:
            existing = conn.execute("SELECT * FROM sovereign_sessions WHERE session_id=%s", (session_id,)).fetchone()
            if existing:
                current = dict(existing)
                if {key: current.get(key) for key in payload} != payload:
                    raise ValueError("session_id already exists with divergent payload")
                return _normalize(current) or {}
            row = conn.execute(
                """INSERT INTO sovereign_sessions(session_id,identity_json,scope,objective,critical_rules,operational_state,
                last_confirmed_action,blockers,pending,next_safe_action,active_authorizations,required_memory_ids)
                VALUES(%s,%s::jsonb,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s) RETURNING *""",
                (session_id, canonical(identity), scope, objective, canonical(critical_rules), canonical(operational_state),
                 last_confirmed_action, canonical(blockers), canonical(pending), next_safe_action,
                 canonical(active_authorizations), payload["required_memory_ids"]),
            ).fetchone()
            self.store._audit(conn, "SESSION_CREATED", session_id, {"scope": scope, "objective_sha256": sha256_json(objective)})
            return _normalize(dict(row)) or {}

    def session(self, session_id: str) -> dict[str, Any]:
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM sovereign_sessions WHERE session_id=%s", (session_id,)).fetchone()
        if not row:
            raise FileNotFoundError(session_id)
        return _normalize(dict(row)) or {}

    def create_binding(self, *, session_id: str, provider: str, external_session_ref: str, status: str = "CURRENT") -> dict[str, Any]:
        require_canonical_mutation('session.bind')
        status = status.upper()
        if status not in {"CURRENT", "PENDING_VALIDATION"}:
            raise ValueError("invalid initial binding status")
        with self.store.connection() as conn:
            if not conn.execute("SELECT 1 FROM sovereign_sessions WHERE session_id=%s", (session_id,)).fetchone():
                raise FileNotFoundError(session_id)
            normalized = normalize_external_session_ref(provider, external_session_ref)
            existing = conn.execute(
                "SELECT * FROM external_session_bindings WHERE lower(provider)=lower(%s) AND canonical_external_ref=%s ORDER BY created_at DESC LIMIT 1",
                (normalized["provider"], normalized["canonical_external_ref"]),
            ).fetchone()
            if existing:
                if existing["session_id"] != session_id:
                    raise ValueError("external session ref already bound to another sovereign session")
                return _normalize(dict(existing)) or {}
            binding_id = f"bind-{uuid.uuid4().hex}"
            row = conn.execute(
                "INSERT INTO external_session_bindings(binding_id,session_id,provider,external_session_ref,canonical_external_ref,external_project_ref,status) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (binding_id, session_id, normalized["provider"], normalized["external_session_ref"], normalized["canonical_external_ref"], normalized["external_project_ref"], status),
            ).fetchone()
            self.store._audit(conn, "EXTERNAL_SESSION_BOUND", binding_id, {"session_id": session_id, "provider": provider, "status": status})
            return _normalize(dict(row)) or {}

    def capture_external_conversation(
        self, *, provider: str, external_session_ref: str, objective: str,
        messages: list[dict[str, Any]], project_id: str | None = None,
        capture_source: str = "INVISIBLE_BROWSER_LEARNING",
    ) -> dict[str, Any]:
        require_canonical_mutation('conversation.capture')
        normalized = normalize_external_session_ref(provider, external_session_ref)
        canonical_ref = str(normalized["canonical_external_ref"])
        logical_project = project_id
        if not logical_project and normalized.get("external_project_ref"):
            logical_project = str(normalized["external_project_ref"]).replace("g/g-p-", "", 1)
        session_id = "ext-" + sha256_json({"provider": provider.casefold(), "canonical_external_ref": canonical_ref})[:32]
        identity = {
            "provider": provider,
            "external_session_ref": normalized["external_session_ref"],
            "canonical_external_ref": canonical_ref,
            "external_project_ref": normalized.get("external_project_ref"),
            "capture_source": capture_source,
        }
        with self.store.connection() as conn:
            existing_session = conn.execute("SELECT session_id FROM sovereign_sessions WHERE session_id=%s", (session_id,)).fetchone()
        if not existing_session:
            self.create_session(
                session_id=session_id, identity=identity, scope=logical_project or "EXTERNAL", objective=objective,
                critical_rules=["SOURCE_EXTERNAL", "PRESERVE_PROVENANCE", "NO_SILENT_FABRICATION"],
                operational_state={"capture_status": "CAPTURING", "captured_messages": 0},
                last_confirmed_action=None, blockers=[], pending=[], next_safe_action="CONTINUE_CAPTURE",
                active_authorizations=[], required_memory_ids=[],
            )
        binding = self.create_binding(session_id=session_id, provider=provider, external_session_ref=external_session_ref)
        memory_ids: list[str] = []
        normalized_messages: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            role = str(message.get("role") or "unknown").strip().lower()
            content_text = str(message.get("text") or message.get("content") or "").strip()
            if not content_text:
                continue
            source_message_id = str(message.get("message_id") or "").strip()
            if not source_message_id:
                source_message_id = sha256_json({"role": role, "text": content_text, "index": index})[:32]
            memory_key = f"external.{provider.casefold()}.{canonical_ref}.message.{source_message_id}"
            item_id = CanonicalMutationService(self.store, actor_id="external-conversation-capture").remember_internal(
                actor_id="external-conversation-capture", source=provider, trusted=False,
                provenance={"external_session_ref": normalized["external_session_ref"], "canonical_external_ref": canonical_ref, "capture_source": capture_source, "ordinal": index},
                namespace="EXTERNAL_CONVERSATION", memory_key=memory_key, category="OBSERVATION",
                content={"provider": provider, "conversation_id": canonical_ref, "role": role, "text": content_text, "ordinal": index, "source_message_id": source_message_id},
                content_text=content_text, confidence=1.0, source_version=None,
                tags=["EXTERNAL_CONVERSATION", provider.upper(), "CAPTURED"],
                idempotency_key=f"capture:{provider.casefold()}:{canonical_ref}:{source_message_id}",
                memory_scope="SESSION", memory_scope_ref=session_id,
            sharing_scope="PROJECT_SHARED" if logical_project else "SYSTEM_SHARED", project_id=logical_project,
            )
            memory_ids.append(item_id)
            normalized_messages.append({"role": role, "text": content_text, "source_message_id": source_message_id, "memory_id": item_id})
        transcript_sha = sha256_json([{k:v for k,v in m.items() if k != "memory_id"} for m in normalized_messages])
        checkpoint_id = "scp-ext-" + sha256_json({"session_id": session_id, "transcript_sha256": transcript_sha})[:32]
        state = {
            "provider": provider, "canonical_external_ref": canonical_ref, "external_session_ref": normalized["external_session_ref"],
            "external_project_ref": normalized.get("external_project_ref"), "project_id": logical_project,
            "captured_messages": len(normalized_messages), "memory_ids": memory_ids, "transcript_sha256": transcript_sha,
            "capture_source": capture_source, "capture_status": "CAPTURED",
        }
        state_sha = sha256_json(state)
        context = {
            "session_id": session_id, "identity": identity, "scope": logical_project or "EXTERNAL", "objective": objective,
            "operational_state": state, "required_memory_ids": memory_ids,
            "last_confirmed_action": "EXTERNAL_CONVERSATION_CAPTURED", "blockers": [], "pending": [],
            "next_safe_action": "RESUME_FROM_CONTEXT_PACK",
        }
        context_sha = sha256_json(context)
        context_pack_id = "ctx-ext-" + context_sha[:32]
        with self.store.connection() as conn:
            conn.execute(
                "INSERT INTO session_checkpoints(checkpoint_id,session_id,state_json,state_sha256,last_event_id) VALUES(%s,%s,%s::jsonb,%s,%s) ON CONFLICT(checkpoint_id) DO NOTHING",
                (checkpoint_id, session_id, canonical(state), state_sha, memory_ids[-1] if memory_ids else None),
            )
            conn.execute(
                "INSERT INTO context_packs(context_pack_id,session_id,checkpoint_id,context_json,context_sha256,required_memory_ids) VALUES(%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT(context_pack_id) DO NOTHING",
                (context_pack_id, session_id, checkpoint_id, canonical(context), context_sha, memory_ids),
            )
            conn.execute(
                "UPDATE sovereign_sessions SET identity_json=%s::jsonb,scope=%s,objective=%s,operational_state=%s::jsonb,last_confirmed_action=%s,blockers='[]'::jsonb,pending='[]'::jsonb,next_safe_action=%s,required_memory_ids=%s,updated_at=now() WHERE session_id=%s",
                (canonical(identity), logical_project or "EXTERNAL", objective, canonical(state), "EXTERNAL_CONVERSATION_CAPTURED", "RESUME_FROM_CONTEXT_PACK", memory_ids, session_id),
            )
            self.store._audit(conn, "EXTERNAL_CONVERSATION_CAPTURED", session_id, {"provider": provider, "canonical_external_ref": canonical_ref, "message_count": len(normalized_messages), "checkpoint_id": checkpoint_id, "context_pack_id": context_pack_id, "context_sha256": context_sha})
        resolved = self.resolve_external_session(provider=provider, external_session_ref=external_session_ref)
        return {**resolved, "captured_messages": len(normalized_messages), "memory_ids": memory_ids, "checkpoint_id": checkpoint_id, "context_pack_id": context_pack_id, "context_sha256": context_sha, "transcript_sha256": transcript_sha, "binding_id": binding["binding_id"]}

    def resolve_external_session(self, *, provider: str, external_session_ref: str) -> dict[str, Any]:
        normalized = normalize_external_session_ref(provider, external_session_ref)
        with self.store.connection() as conn:
            row = conn.execute(
                """SELECT * FROM external_session_bindings
                   WHERE lower(provider)=lower(%s) AND canonical_external_ref=%s
                   ORDER BY CASE status WHEN 'CURRENT' THEN 0 WHEN 'VALIDATED' THEN 1 WHEN 'PENDING_VALIDATION' THEN 2 ELSE 3 END, created_at DESC
                   LIMIT 1""",
                (normalized["provider"], normalized["canonical_external_ref"]),
            ).fetchone()
        if not row:
            return {**normalized, "found": False, "reason": "NOT_CAPTURED", "recoverable": False}
        binding = _normalize(dict(row)) or {}
        resume = self.resume_session(str(binding["session_id"]))
        return {
            **normalized,
            "found": True,
            "reason": "FOUND",
            "recoverable": bool(
                resume.get("checkpoint")
                and resume.get("context_pack", {}).get("context_pack_id")
                and resume.get("integrity", {}).get("all_valid") is True
            ),
            "binding": binding,
            "session_id": binding["session_id"],
            "resume": resume,
        }

    def current_binding(self, session_id: str) -> dict[str, Any]:
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM external_session_bindings WHERE session_id=%s AND status='CURRENT'", (session_id,)).fetchone()
        if not row:
            raise FileNotFoundError(f"current binding not found: {session_id}")
        return _normalize(dict(row)) or {}

    def resume_session(self, session_id: str) -> dict[str, Any]:
        with self.store.connection() as conn:
            session = conn.execute("SELECT * FROM sovereign_sessions WHERE session_id=%s", (session_id,)).fetchone()
            if not session:
                raise FileNotFoundError(session_id)
            binding = conn.execute(
                "SELECT * FROM external_session_bindings WHERE session_id=%s AND status='CURRENT' ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            checkpoint = conn.execute(
                "SELECT * FROM session_checkpoints WHERE session_id=%s ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            context_pack = None
            if checkpoint:
                context_pack = conn.execute(
                    "SELECT * FROM context_packs WHERE session_id=%s AND checkpoint_id=%s ORDER BY created_at DESC LIMIT 1",
                    (session_id, checkpoint["checkpoint_id"]),
                ).fetchone()
            rotations = conn.execute(
                "SELECT rotation_id,status,checkpoint_id,context_pack_id,updated_at FROM session_rotations "
                "WHERE session_id=%s AND status NOT IN ('COMPLETED','ABORTED') ORDER BY requested_at",
                (session_id,),
            ).fetchall()

        session_dict = _normalize(dict(session)) or {}
        base_context = {
            "session_id": session_dict["session_id"],
            "identity": session_dict["identity_json"],
            "scope": session_dict["scope"],
            "objective": session_dict["objective"],
            "critical_rules": session_dict["critical_rules"],
            "operational_state": session_dict["operational_state"],
            "last_confirmed_action": session_dict["last_confirmed_action"],
            "blockers": session_dict["blockers"],
            "pending": session_dict["pending"],
            "next_safe_action": session_dict["next_safe_action"],
            "active_authorizations": session_dict["active_authorizations"],
            "required_memory_ids": list(session_dict.get("required_memory_ids") or []),
        }
        checkpoint_dict = _normalize(dict(checkpoint)) if checkpoint else None
        context_pack_dict = _normalize(dict(context_pack)) if context_pack else None
        if context_pack_dict:
            context = context_pack_dict["context_json"]
            context_sha256 = context_pack_dict["context_sha256"]
            context_pack_id = context_pack_dict["context_pack_id"]
        else:
            context = base_context
            context_sha256 = sha256_json(context)
            context_pack_id = None

        checkpoint_integrity = True
        if checkpoint_dict:
            checkpoint_integrity = sha256_json(checkpoint_dict["state_json"]) == checkpoint_dict["state_sha256"]
        context_integrity = sha256_json(context) == context_sha256
        return {
            "session": session_dict,
            "current_binding": _normalize(dict(binding)) if binding else None,
            "checkpoint": checkpoint_dict,
            "context_pack": {
                "context_pack_id": context_pack_id,
                "checkpoint_id": checkpoint_dict["checkpoint_id"] if checkpoint_dict else None,
                "context": context,
                "context_sha256": context_sha256,
                "required_memory_ids": list(context.get("required_memory_ids") or []),
            },
            "integrity": {
                "checkpoint_sha256_valid": checkpoint_integrity,
                "context_sha256_valid": context_integrity,
                "all_valid": checkpoint_integrity and context_integrity,
            },
            "incomplete_rotations": [_normalize(dict(row)) for row in rotations],
        }

    def request_rotation(self, *, session_id: str, safe_point: dict[str, Any], memory_before_mb: float | None, reason: str) -> dict[str, Any]:
        require_canonical_mutation('rotation.request')
        with self.store.connection() as conn:
            old = conn.execute("SELECT * FROM external_session_bindings WHERE session_id=%s AND status='CURRENT'", (session_id,)).fetchone()
            if not old:
                raise FileNotFoundError(f"current binding not found: {session_id}")
            active = conn.execute("SELECT * FROM session_rotations WHERE session_id=%s AND status NOT IN ('COMPLETED','ABORTED') ORDER BY requested_at DESC LIMIT 1", (session_id,)).fetchone()
            if active:
                return _normalize(dict(active)) or {}
            rotation_id = f"rot-{uuid.uuid4().hex}"
            status = "REQUESTED" if safe_point_ready(safe_point) else "WAITING_SAFE_POINT"
            row = conn.execute(
                "INSERT INTO session_rotations(rotation_id,session_id,old_binding_id,status,reason,safe_point_json,memory_before_mb) VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING *",
                (rotation_id, session_id, old["binding_id"], status, reason, canonical(safe_point), memory_before_mb),
            ).fetchone()
            self.store._audit(conn, "SESSION_ROTATION_REQUESTED", rotation_id, {"session_id": session_id, "status": status, "safe_point": safe_point})
            return _normalize(dict(row)) or {}

    def update_safe_point(self, rotation_id: str, safe_point: dict[str, Any]) -> dict[str, Any]:
        require_canonical_mutation('rotation.safe_point')
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM session_rotations WHERE rotation_id=%s FOR UPDATE", (rotation_id,)).fetchone()
            if not row:
                raise FileNotFoundError(rotation_id)
            if row["status"] not in {"REQUESTED", "WAITING_SAFE_POINT"}:
                raise ValueError(f"safe point cannot be changed from {row['status']}")
            status = "REQUESTED" if safe_point_ready(safe_point) else "WAITING_SAFE_POINT"
            updated = conn.execute("UPDATE session_rotations SET status=%s,safe_point_json=%s::jsonb,updated_at=now() WHERE rotation_id=%s RETURNING *", (status, canonical(safe_point), rotation_id)).fetchone()
            self.store._audit(conn, "SESSION_ROTATION_SAFE_POINT", rotation_id, {"status": status, "safe_point": safe_point})
            return _normalize(dict(updated)) or {}

    def prepare_rotation(self, rotation_id: str, *, last_event_id: str | None = None) -> dict[str, Any]:
        require_canonical_mutation('rotation.prepare')
        with self.store.connection() as conn:
            rotation = conn.execute("SELECT * FROM session_rotations WHERE rotation_id=%s FOR UPDATE", (rotation_id,)).fetchone()
            if not rotation:
                raise FileNotFoundError(rotation_id)
            if rotation["status"] != "REQUESTED":
                raise ValueError(f"rotation not ready for checkpoint: {rotation['status']}")
            if not safe_point_ready(dict(rotation["safe_point_json"])):
                raise ValueError("safe point not satisfied")
            session = conn.execute("SELECT * FROM sovereign_sessions WHERE session_id=%s", (rotation["session_id"],)).fetchone()
            if not session:
                raise FileNotFoundError(rotation["session_id"])
            state = {
                "session_id": session["session_id"],
                "identity": session["identity_json"],
                "scope": session["scope"],
                "objective": session["objective"],
                "critical_rules": session["critical_rules"],
                "operational_state": session["operational_state"],
                "last_confirmed_action": session["last_confirmed_action"],
                "blockers": session["blockers"],
                "pending": session["pending"],
                "next_safe_action": session["next_safe_action"],
                "active_authorizations": session["active_authorizations"],
                "required_memory_ids": list(session["required_memory_ids"] or []),
            }
            checkpoint_id = f"scp-{uuid.uuid4().hex}"
            state_hash = sha256_json(state)
            conn.execute("INSERT INTO session_checkpoints(checkpoint_id,session_id,state_json,state_sha256,last_event_id) VALUES(%s,%s,%s::jsonb,%s,%s)", (checkpoint_id, session["session_id"], canonical(state), state_hash, last_event_id))
            context = {**state, "checkpoint_id": checkpoint_id, "checkpoint_sha256": state_hash, "old_binding_id": rotation["old_binding_id"], "rotation_id": rotation_id}
            context_pack_id = f"ctx-{uuid.uuid4().hex}"
            context_hash = sha256_json(context)
            conn.execute("INSERT INTO context_packs(context_pack_id,session_id,checkpoint_id,context_json,context_sha256,required_memory_ids) VALUES(%s,%s,%s,%s::jsonb,%s,%s)", (context_pack_id, session["session_id"], checkpoint_id, canonical(context), context_hash, list(session["required_memory_ids"] or [])))
            required_sources=[str(x) for x in (session["required_memory_ids"] or []) if str(x)]
            if required_sources:
                self.store._register_derived_artifact_in_conn(conn,artifact_type="SESSION_CHECKPOINT",artifact_ref=checkpoint_id,artifact_sha256=state_hash,sources=required_sources,metadata={"session_id":str(session["session_id"]),"rotation_id":rotation_id})
                self.store._register_derived_artifact_in_conn(conn,artifact_type="CONTEXT_PACK",artifact_ref=context_pack_id,artifact_sha256=context_hash,sources=required_sources,metadata={"session_id":str(session["session_id"]),"checkpoint_id":checkpoint_id,"rotation_id":rotation_id})
            updated = conn.execute("UPDATE session_rotations SET checkpoint_id=%s,context_pack_id=%s,status='CHECKPOINTED',updated_at=now() WHERE rotation_id=%s RETURNING *", (checkpoint_id, context_pack_id, rotation_id)).fetchone()
            self.store._audit(conn, "SESSION_ROTATION_CHECKPOINTED", rotation_id, {"checkpoint_id": checkpoint_id, "context_pack_id": context_pack_id, "context_sha256": context_hash})
            return {
                "rotation": _normalize(dict(updated)),
                "context_pack": {
                    "context_pack_id": context_pack_id,
                    "checkpoint_id": checkpoint_id,
                    "context": context,
                    "context_sha256": context_hash,
                    "required_memory_ids": list(session["required_memory_ids"] or []),
                },
            }

    def bind_new_external(self, rotation_id: str, *, provider: str, external_session_ref: str) -> dict[str, Any]:
        require_canonical_mutation('rotation.bind')
        with self.store.connection() as conn:
            rotation = conn.execute("SELECT * FROM session_rotations WHERE rotation_id=%s FOR UPDATE", (rotation_id,)).fetchone()
            if not rotation:
                raise FileNotFoundError(rotation_id)
            if rotation["status"] not in {"CHECKPOINTED", "NEW_BOUND"}:
                raise ValueError(f"rotation not ready for new binding: {rotation['status']}")
            if rotation["new_binding_id"]:
                binding = conn.execute("SELECT * FROM external_session_bindings WHERE binding_id=%s", (rotation["new_binding_id"],)).fetchone()
                return _normalize(dict(binding)) or {}
            binding_id = f"bind-{uuid.uuid4().hex}"
            binding = conn.execute(
                "INSERT INTO external_session_bindings(binding_id,session_id,provider,external_session_ref,status,context_pack_id) VALUES(%s,%s,%s,%s,'PENDING_VALIDATION',%s) RETURNING *",
                (binding_id, rotation["session_id"], provider, external_session_ref, rotation["context_pack_id"]),
            ).fetchone()
            conn.execute("UPDATE session_rotations SET new_binding_id=%s,status='NEW_BOUND',updated_at=now() WHERE rotation_id=%s", (binding_id, rotation_id))
            self.store._audit(conn, "SESSION_ROTATION_NEW_BOUND", rotation_id, {"new_binding_id": binding_id, "provider": provider})
            return _normalize(dict(binding)) or {}

    def context_pack(self, context_pack_id: str) -> dict[str, Any]:
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM context_packs WHERE context_pack_id=%s", (context_pack_id,)).fetchone()
        if not row:
            raise FileNotFoundError(context_pack_id)
        return _normalize(dict(row)) or {}

    def validate_rotation(self, rotation_id: str, *, observed_context_sha256: str,
                          observed_checkpoint_id: str, observed_required_memory_ids: list[str]) -> dict[str, Any]:
        require_canonical_mutation('rotation.validate')
        with self.store.connection() as conn:
            rotation = conn.execute("SELECT * FROM session_rotations WHERE rotation_id=%s FOR UPDATE", (rotation_id,)).fetchone()
            if not rotation:
                raise FileNotFoundError(rotation_id)
            if rotation["status"] != "NEW_BOUND":
                raise ValueError(f"rotation not ready for validation: {rotation['status']}")
            context = conn.execute("SELECT * FROM context_packs WHERE context_pack_id=%s", (rotation["context_pack_id"],)).fetchone()
            if not context:
                raise FileNotFoundError(rotation["context_pack_id"])
            expected_ids = sorted(list(context["required_memory_ids"] or []))
            observed_ids = sorted(set(observed_required_memory_ids))
            checks = {
                "context_sha256": observed_context_sha256 == context["context_sha256"],
                "checkpoint_id": observed_checkpoint_id == context["checkpoint_id"],
                "required_memory_ids": observed_ids == expected_ids,
            }
            if not all(checks.values()):
                reason = "VALIDATION_MISMATCH:" + ",".join(key for key, ok in checks.items() if not ok)
                if rotation["new_binding_id"]:
                    conn.execute("UPDATE external_session_bindings SET status='ABORTED' WHERE binding_id=%s", (rotation["new_binding_id"],))
                updated = conn.execute("UPDATE session_rotations SET status='ABORTED',failure_reason=%s,updated_at=now(),completed_at=now() WHERE rotation_id=%s RETURNING *", (reason, rotation_id)).fetchone()
                self.store._audit(conn, "SESSION_ROTATION_ABORTED", rotation_id, {"reason": reason, "checks": checks})
                return {"validated": False, "checks": checks, "rotation": _normalize(dict(updated))}
            conn.execute("UPDATE external_session_bindings SET status='VALIDATED',validated_at=now() WHERE binding_id=%s", (rotation["new_binding_id"],))
            updated = conn.execute("UPDATE session_rotations SET status='VALIDATED',validated_at=now(),updated_at=now() WHERE rotation_id=%s RETURNING *", (rotation_id,)).fetchone()
            self.store._audit(conn, "SESSION_ROTATION_VALIDATED", rotation_id, {"checks": checks, "context_sha256": context["context_sha256"]})
            return {"validated": True, "checks": checks, "rotation": _normalize(dict(updated))}

    def complete_rotation(self, rotation_id: str, *, memory_after_mb: float | None,
                          client_old_closed: bool, client_close_evidence: dict[str, Any]) -> dict[str, Any]:
        require_canonical_mutation('rotation.complete')
        if not client_old_closed:
            raise ValueError("old client session must be closed only after validation")
        with self.store.connection() as conn:
            rotation = conn.execute("SELECT * FROM session_rotations WHERE rotation_id=%s FOR UPDATE", (rotation_id,)).fetchone()
            if not rotation:
                raise FileNotFoundError(rotation_id)
            if rotation["status"] == "COMPLETED":
                return _normalize(dict(rotation)) or {}
            if rotation["status"] != "VALIDATED":
                raise ValueError(f"rotation cannot complete from {rotation['status']}")
            conn.execute("UPDATE external_session_bindings SET status='SUPERSEDED',superseded_at=now() WHERE binding_id=%s", (rotation["old_binding_id"],))
            conn.execute("UPDATE external_session_bindings SET status='CURRENT' WHERE binding_id=%s", (rotation["new_binding_id"],))
            before = float(rotation["memory_before_mb"]) if rotation["memory_before_mb"] is not None else None
            after = float(memory_after_mb) if memory_after_mb is not None else None
            released = max(before - after, 0.0) if before is not None and after is not None else None
            updated = conn.execute(
                """UPDATE session_rotations SET status='COMPLETED',memory_after_mb=%s,memory_released_mb=%s,
                client_close_evidence=%s::jsonb,completed_at=now(),updated_at=now() WHERE rotation_id=%s RETURNING *""",
                (after, released, canonical(client_close_evidence), rotation_id),
            ).fetchone()
            self.store._audit(conn, "SESSION_ROTATION_COMPLETED", rotation_id, {"memory_before_mb": before, "memory_after_mb": after, "memory_released_mb": released, "client_close_evidence": client_close_evidence})
            return _normalize(dict(updated)) or {}

    def abort_rotation(self, rotation_id: str, *, reason: str) -> dict[str, Any]:
        require_canonical_mutation('rotation.abort')
        with self.store.connection() as conn:
            rotation = conn.execute("SELECT * FROM session_rotations WHERE rotation_id=%s FOR UPDATE", (rotation_id,)).fetchone()
            if not rotation:
                raise FileNotFoundError(rotation_id)
            if rotation["status"] in {"COMPLETED", "ABORTED"}:
                return _normalize(dict(rotation)) or {}
            if rotation["new_binding_id"]:
                conn.execute("UPDATE external_session_bindings SET status='ABORTED' WHERE binding_id=%s", (rotation["new_binding_id"],))
            updated = conn.execute("UPDATE session_rotations SET status='ABORTED',failure_reason=%s,completed_at=now(),updated_at=now() WHERE rotation_id=%s RETURNING *", (reason, rotation_id)).fetchone()
            self.store._audit(conn, "SESSION_ROTATION_ABORTED", rotation_id, {"reason": reason})
            return _normalize(dict(updated)) or {}

    def rotation(self, rotation_id: str) -> dict[str, Any]:
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM session_rotations WHERE rotation_id=%s", (rotation_id,)).fetchone()
        if not row:
            raise FileNotFoundError(rotation_id)
        return _normalize(dict(row)) or {}

    def recovery_plan(self) -> list[dict[str, Any]]:
        action_by_status = {
            "WAITING_SAFE_POINT": "WAIT_FOR_SAFE_POINT",
            "REQUESTED": "PREPARE_CHECKPOINT",
            "CHECKPOINTED": "RETRY_NEW_BINDING",
            "NEW_BOUND": "RETRY_VALIDATION_OR_ABORT",
            "VALIDATED": "COMPLETE_IDEMPOTENTLY",
        }
        with self.store.connection() as conn:
            rows = conn.execute("SELECT * FROM session_rotations WHERE status NOT IN ('COMPLETED','ABORTED') ORDER BY requested_at").fetchall()
        return [{"rotation": _normalize(dict(row)), "recovery_action": action_by_status.get(row["status"], "INSPECT")} for row in rows]
