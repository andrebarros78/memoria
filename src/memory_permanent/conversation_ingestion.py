from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .canonical_mutation import CanonicalMutationService, require_canonical_mutation
from .session_rotation import (
    SessionRotationRepository,
    _normalize,
    normalize_external_session_ref,
)
from .store import PostgresMemoryStore, canonical, sha256_json
from .temporal import normalize_temporal_envelope

logger = logging.getLogger(__name__)


class ConversationIngestionRepository:
    """Durable write-through ingestion for external conversation turns."""

    def __init__(self, store: PostgresMemoryStore) -> None:
        self.store = store
        self.sessions = SessionRotationRepository(store, initialize=False)

    def enqueue_turn(
        self, *, provider: str, external_session_ref: str, objective: str,
        role: str, text: str, message_id: str, ordinal: int,
        project_id: str | None = None, capture_source: str = "CONVERSATION_RUNTIME",
        process_now: bool = True, occurred_at: datetime | None = None, observed_at: datetime | None = None,
        valid_from: datetime | None = None, valid_to: datetime | None = None,
    ) -> dict[str, Any]:
        require_canonical_mutation('conversation.enqueue')
        normalized = normalize_external_session_ref(provider, external_session_ref)
        canonical_ref = str(normalized["canonical_external_ref"])
        role_value = str(role or "").strip().lower()
        text_value = str(text or "").strip()
        message_value = str(message_id or "").strip()
        if not role_value or not text_value or not message_value:
            raise ValueError("role, text and message_id are required")
        ordinal_value = int(ordinal)
        if ordinal_value < 0:
            raise ValueError("ordinal must be non-negative")
        logical_project = project_id
        if not logical_project and normalized.get("external_project_ref"):
            logical_project = str(normalized["external_project_ref"]).replace("g/g-p-", "", 1)
        if logical_project and self.store.access.agent_id != "__SYSTEM__" and self.store.access.project_id != logical_project:
            raise PermissionError("project-scoped conversation ingestion requires matching authorized project context")
        temporal = normalize_temporal_envelope(occurred_at=occurred_at, observed_at=observed_at, valid_from=valid_from, valid_to=valid_to)
        content_sha = sha256_json({"role": role_value, "text": text_value})
        event_id = "ing-" + sha256_json({
            "tenant": self.store.tenant_id, "provider": provider.casefold(),
            "conversation": canonical_ref, "message_id": message_value,
        })[:32]
        with self.store.connection() as conn:
            row = conn.execute("""SELECT e.*,t.occurred_at,t.observed_at,t.valid_from,t.valid_to,t.created_at AS temporal_created_at
                FROM conversation_ingestion_events e LEFT JOIN conversation_ingestion_event_temporal t ON t.event_id=e.event_id
                WHERE e.event_id=%s""", (event_id,)).fetchone()
            if row:
                current = dict(row)
                if str(current["content_sha256"]) != content_sha or str(current["role"]) != role_value or int(current["ordinal"]) != ordinal_value:
                    raise ValueError("message_id already exists with divergent conversation payload")
                existing_t = conn.execute("SELECT occurred_at,observed_at,valid_from,valid_to FROM conversation_ingestion_event_temporal WHERE event_id=%s",(event_id,)).fetchone()
                if existing_t and (existing_t["occurred_at"] != temporal.occurred_at or existing_t["observed_at"] != temporal.observed_at or existing_t["valid_from"] != temporal.valid_from or existing_t["valid_to"] != temporal.valid_to):
                    raise ValueError("message_id already exists with divergent temporal envelope")
            else:
                row = conn.execute(
                    """INSERT INTO conversation_ingestion_events(
                    event_id,provider,external_session_ref,canonical_external_ref,external_project_ref,message_id,role,ordinal,
                    content_text,content_sha256,objective,project_id,capture_source,status)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING') RETURNING *""",
                    (event_id, normalized["provider"], normalized["external_session_ref"], canonical_ref,
                     normalized.get("external_project_ref"), message_value, role_value, ordinal_value,
                     text_value, content_sha, objective, logical_project, capture_source),
                ).fetchone()
                conn.execute("""INSERT INTO conversation_ingestion_event_temporal(event_id,tenant_id,occurred_at,observed_at,valid_from,valid_to)
                    VALUES(%s,%s,%s,%s,%s,%s)""",(event_id,self.store.tenant_id,temporal.occurred_at,temporal.observed_at,temporal.valid_from,temporal.valid_to))
                self.store._audit(conn, "CONVERSATION_TURN_ENQUEUED", event_id, {
                    "provider": provider, "canonical_external_ref": canonical_ref,
                    "message_id": message_value, "ordinal": ordinal_value, "temporal": temporal.as_dict(),
                })
        if process_now:
            return self.process_event(event_id)
        return self.event(event_id)

    def event(self, event_id: str) -> dict[str, Any]:
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM conversation_ingestion_events WHERE event_id=%s", (event_id,)).fetchone()
        if not row:
            raise FileNotFoundError(event_id)
        result = _normalize(dict(row)) or {}
        result.pop("content_text", None)
        return result

    def _persist_turn(self, row: dict[str, Any]) -> dict[str, Any]:
        require_canonical_mutation('conversation.persist')
        provider = str(row["provider"])
        external_ref = str(row["external_session_ref"])
        canonical_ref = str(row["canonical_external_ref"])
        project_id = str(row["project_id"]) if row.get("project_id") else None
        session_id = "ext-" + sha256_json({"provider": provider.casefold(), "canonical_external_ref": canonical_ref})[:32]
        with self.store.connection() as conn:
            temporal_row = conn.execute("SELECT occurred_at,observed_at,valid_from,valid_to FROM conversation_ingestion_event_temporal WHERE event_id=%s",(row["event_id"],)).fetchone()
        if not temporal_row:
            raise RuntimeError("conversation temporal sidecar missing")
        identity = {
            "provider": provider, "external_session_ref": external_ref,
            "canonical_external_ref": canonical_ref,
            "external_project_ref": row.get("external_project_ref"),
            "capture_source": str(row["capture_source"]),
        }
        with self.store.connection() as conn:
            exists = conn.execute("SELECT 1 FROM sovereign_sessions WHERE session_id=%s", (session_id,)).fetchone()
        if not exists:
            self.sessions.create_session(
                session_id=session_id, identity=identity, scope=project_id or "EXTERNAL", objective=str(row["objective"]),
                critical_rules=["SOURCE_EXTERNAL","PRESERVE_PROVENANCE","NO_SILENT_FABRICATION","TURN_WRITE_THROUGH"],
                operational_state={"capture_status":"CAPTURING","captured_messages":0,"ingestion_mode":"INCREMENTAL"},
                last_confirmed_action=None, blockers=[], pending=[], next_safe_action="CONTINUE_CAPTURE",
                active_authorizations=[], required_memory_ids=[],
            )
        binding = self.sessions.create_binding(session_id=session_id, provider=provider, external_session_ref=external_ref)
        item_id = CanonicalMutationService(self.store, actor_id="conversation-runtime-ingestion").remember_internal(
            actor_id="conversation-runtime-ingestion", source=provider, trusted=False,
            provenance={"external_session_ref":external_ref,"canonical_external_ref":canonical_ref,
                        "capture_source":row["capture_source"],"ordinal":int(row["ordinal"]),"ingestion_mode":"INCREMENTAL"},
            namespace="EXTERNAL_CONVERSATION",
            memory_key=f"external.{provider.casefold()}.{canonical_ref}.message.{row['message_id']}", category="OBSERVATION",
            content={"provider":provider,"conversation_id":canonical_ref,"role":row["role"],"text":row["content_text"],
                     "ordinal":int(row["ordinal"]),"source_message_id":row["message_id"]},
            content_text=str(row["content_text"]), confidence=1.0,
            tags=["EXTERNAL_CONVERSATION",provider.upper(),"CAPTURED","WRITE_THROUGH"],
            idempotency_key=f"turn:{provider.casefold()}:{canonical_ref}:{row['message_id']}",
            memory_scope="SESSION", memory_scope_ref=session_id,
            sharing_scope="PROJECT_SHARED" if project_id else "SYSTEM_SHARED", project_id=project_id,
            occurred_at=temporal_row["occurred_at"], observed_at=temporal_row["observed_at"],
            valid_from=temporal_row["valid_from"], valid_to=temporal_row["valid_to"],
        )
        duplicate = False
        with self.store.connection() as conn:
            session = conn.execute("SELECT * FROM sovereign_sessions WHERE session_id=%s FOR UPDATE", (session_id,)).fetchone()
            if not session:
                raise FileNotFoundError(session_id)
            required = list(session["required_memory_ids"] or [])
            if item_id in required:
                duplicate = True
            else:
                required.append(item_id)
                rows = conn.execute(
                    "SELECT item_id,content_json,content_text FROM memory_items WHERE item_id=ANY(%s)", (required,)
                ).fetchall()
                by_id = {str(x["item_id"]): dict(x) for x in rows}
                ordered: list[tuple[int,int,str,dict[str,Any]]] = []
                for pos, mid in enumerate(required):
                    data = by_id.get(str(mid))
                    if data is None:
                        continue
                    content = dict(data.get("content_json") or {})
                    raw_ordinal = content.get("ordinal")
                    try:
                        msg_ordinal = int(raw_ordinal) if isinstance(raw_ordinal, (str, int, float)) else pos
                    except (TypeError, ValueError):
                        msg_ordinal = pos
                    ordered.append((msg_ordinal,pos,str(mid),content))
                ordered.sort(key=lambda x:(x[0],x[1]))
                required = [x[2] for x in ordered]
                transcript = [
                    {"role":str(x[3].get("role") or "unknown"),
                     "text":str(x[3].get("text") or by_id[x[2]].get("content_text") or ""),
                     "source_message_id":str(x[3].get("source_message_id") or ""),"ordinal":x[0]}
                    for x in ordered
                ]
                transcript_sha = sha256_json(transcript)
                state = {
                    "provider":provider,"canonical_external_ref":canonical_ref,"external_session_ref":external_ref,
                    "external_project_ref":row.get("external_project_ref"),"project_id":project_id,
                    "captured_messages":len(required),"memory_ids":required,"transcript_sha256":transcript_sha,
                    "capture_source":row["capture_source"],"capture_status":"CAPTURED","ingestion_mode":"INCREMENTAL",
                    "last_message_id":row["message_id"],"last_ordinal":int(row["ordinal"]),
                }
                state_sha = sha256_json(state)
                checkpoint_id = "scp-turn-" + sha256_json({"session_id":session_id,"transcript_sha256":transcript_sha})[:32]
                context = {
                    "session_id":session_id,"identity":identity,"scope":project_id or "EXTERNAL","objective":str(row["objective"]),
                    "operational_state":state,"required_memory_ids":required,"last_confirmed_action":"CONVERSATION_TURN_PERSISTED",
                    "blockers":[],"pending":[],"next_safe_action":"RESUME_FROM_CONTEXT_PACK",
                }
                context_sha = sha256_json(context)
                context_pack_id = "ctx-turn-" + context_sha[:32]
                conn.execute(
                    "INSERT INTO session_checkpoints(checkpoint_id,session_id,state_json,state_sha256,last_event_id) VALUES(%s,%s,%s::jsonb,%s,%s) ON CONFLICT(checkpoint_id) DO NOTHING",
                    (checkpoint_id,session_id,canonical(state),state_sha,item_id),
                )
                conn.execute(
                    "INSERT INTO context_packs(context_pack_id,session_id,checkpoint_id,context_json,context_sha256,required_memory_ids) VALUES(%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT(context_pack_id) DO NOTHING",
                    (context_pack_id,session_id,checkpoint_id,canonical(context),context_sha,required),
                )
                conn.execute(
                    "UPDATE sovereign_sessions SET identity_json=%s::jsonb,scope=%s,objective=%s,operational_state=%s::jsonb,last_confirmed_action=%s,blockers='[]'::jsonb,pending='[]'::jsonb,next_safe_action=%s,required_memory_ids=%s,updated_at=now() WHERE session_id=%s",
                    (canonical(identity),project_id or "EXTERNAL",str(row["objective"]),canonical(state),
                     "CONVERSATION_TURN_PERSISTED","RESUME_FROM_CONTEXT_PACK",required,session_id),
                )
                self.store._audit(conn,"CONVERSATION_TURN_PERSISTED",session_id,{
                    "provider":provider,"canonical_external_ref":canonical_ref,"message_id":row["message_id"],
                    "ordinal":int(row["ordinal"]),"memory_id":item_id,"checkpoint_id":checkpoint_id,
                    "context_pack_id":context_pack_id,"context_sha256":context_sha,
                })
        resolved = self.resolve(provider=provider, external_session_ref=external_ref)
        return {**resolved,"memory_id":item_id,"duplicate":duplicate,"binding_id":binding["binding_id"]}

    def _conversation_payload(self, required_memory_ids: list[str]) -> dict[str, Any]:
        ids = list(dict.fromkeys(str(x) for x in required_memory_ids if str(x).strip()))
        if not ids:
            return {"messages":[],"message_count":0,"missing_memory_ids":[],"all_messages_integrity_valid":True}
        with self.store.connection() as conn:
            rows = conn.execute(
                "SELECT item_id,content_json,content_text,content_sha256,created_at FROM memory_items WHERE item_id=ANY(%s)",(ids,)
            ).fetchall()
        by_id = {str(x["item_id"]):dict(x) for x in rows}
        messages: list[dict[str, Any]]=[]; missing=[]; valid=True
        for pos, mid in enumerate(ids):
            data=by_id.get(mid)
            if data is None:
                missing.append(mid); valid=False; continue
            content=dict(data.get("content_json") or {})
            if sha256_json(content) != str(data.get("content_sha256") or ""):
                valid=False
            raw_ordinal=content.get("ordinal")
            try: ordinal=int(raw_ordinal) if isinstance(raw_ordinal,(str,int,float)) else pos
            except (TypeError,ValueError): ordinal=pos
            created=data.get("created_at")
            messages.append({"memory_id":mid,"message_id":str(content.get("source_message_id") or ""),
                             "role":str(content.get("role") or "unknown"),"text":str(data.get("content_text") or ""),
                             "ordinal":ordinal,"content_sha256":str(data.get("content_sha256") or ""),
                             "created_at":created.isoformat() if isinstance(created,datetime) else created})
        messages.sort(key=lambda x:x["ordinal"])
        return {"messages":messages,"message_count":len(messages),"missing_memory_ids":missing,
                "all_messages_integrity_valid":valid and not missing}

    def resolve(self, *, provider: str, external_session_ref: str) -> dict[str, Any]:
        base = self.sessions.resolve_external_session(provider=provider, external_session_ref=external_session_ref)
        if not base.get("found"):
            return base
        resume = base.get("resume") or {}
        required = list((resume.get("session") or {}).get("required_memory_ids") or [])
        conversation = self._conversation_payload(required)
        payload = {
            "provider":base.get("provider"),"conversation_id":base.get("canonical_external_ref"),
            "project_ref":(base.get("binding") or {}).get("external_project_ref"),"session_id":base.get("session_id"),
            "objective":(resume.get("session") or {}).get("objective"),
            "last_confirmed_action":(resume.get("session") or {}).get("last_confirmed_action"),
            "next_safe_action":(resume.get("session") or {}).get("next_safe_action"),
            "checkpoint_id":(resume.get("checkpoint") or {}).get("checkpoint_id"),
            "context_pack_id":(resume.get("context_pack") or {}).get("context_pack_id"),**conversation,
        }
        recoverable=bool(base.get("recoverable") and conversation["all_messages_integrity_valid"] and conversation["message_count"]>0)
        return {**base,"recoverable":recoverable,"reason":"FOUND" if recoverable else "INCOMPLETE_CAPTURE",
                "continuation_payload":payload}

    def process_event(self, event_id: str, *, max_attempts: int = 10) -> dict[str, Any]:
        require_canonical_mutation('conversation.process')
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM conversation_ingestion_events WHERE event_id=%s FOR UPDATE",(event_id,)).fetchone()
            if not row:
                raise FileNotFoundError(event_id)
            if row["status"] == "PROCESSED":
                return self.event(event_id)
            attempts=int(row["attempt_count"] or 0)+1
            if attempts > max_attempts:
                conn.execute("UPDATE conversation_ingestion_events SET status='DEAD_LETTER',updated_at=now() WHERE event_id=%s",(event_id,))
                return self.event(event_id)
            row=conn.execute(
                "UPDATE conversation_ingestion_events SET status='PROCESSING',attempt_count=%s,last_error=NULL,updated_at=now() WHERE event_id=%s RETURNING *",
                (attempts,event_id),
            ).fetchone()
        try:
            result=self._persist_turn(dict(row))
        except Exception as exc:
            delay=min(3600,5*(2 ** max(attempts-1,0)))
            status="DEAD_LETTER" if attempts >= max_attempts else "FAILED"
            error=f"{type(exc).__name__}: {exc!s}"[:500]
            error = str(CanonicalMutationService(self.store, actor_id="conversation-runtime-ingestion").sanitize(error)[0])
            with self.store.connection() as conn:
                conn.execute(
                    "UPDATE conversation_ingestion_events SET status=%s,last_error=%s,next_attempt_at=now()+(%s * interval '1 second'),updated_at=now() WHERE event_id=%s",
                    (status,error,delay,event_id),
                )
                self.store._audit(conn,"CONVERSATION_TURN_INGESTION_FAILED",event_id,{"status":status,"attempt":attempts,"error_type":type(exc).__name__})
            raise
        with self.store.connection() as conn:
            updated=conn.execute(
                """UPDATE conversation_ingestion_events SET status='PROCESSED',last_error=NULL,
                memory_id=%s,session_id=%s,checkpoint_id=%s,context_pack_id=%s,processed_at=now(),updated_at=now()
                WHERE event_id=%s RETURNING *""",
                (result.get("memory_id"),result.get("session_id"),
                 ((result.get("resume") or {}).get("checkpoint") or {}).get("checkpoint_id"),
                 ((result.get("resume") or {}).get("context_pack") or {}).get("context_pack_id"),event_id),
            ).fetchone()
            self.store._audit(conn,"CONVERSATION_TURN_INGESTED",event_id,{
                "session_id":result.get("session_id"),"memory_id":result.get("memory_id"),
                "duplicate":bool(result.get("duplicate")),"recoverable":bool(result.get("recoverable")),
            })
        response=_normalize(dict(updated)) or {}
        response.pop("content_text",None)
        response["recovery"]={"found":result.get("found"),"recoverable":result.get("recoverable"),
                              "session_id":result.get("session_id"),"continuation_payload":result.get("continuation_payload")}
        return response

    def retry_pending(self, *, limit: int = 100) -> dict[str, Any]:
        require_canonical_mutation('conversation.retry')
        limit=max(1,min(int(limit),500))
        with self.store.connection() as conn:
            rows=conn.execute(
                """SELECT event_id FROM conversation_ingestion_events
                WHERE status IN ('PENDING','FAILED') AND next_attempt_at<=now()
                ORDER BY created_at LIMIT %s""",(limit,)
            ).fetchall()
        processed=0; failed=0; ids=[]
        for item in rows:
            event_id=str(item["event_id"]); ids.append(event_id)
            try:
                self.process_event(event_id); processed+=1
            except Exception:
                logger.exception("conversation ingestion retry failed", extra={"event_id": event_id})
                failed+=1
        return {"selected":len(rows),"processed":processed,"failed":failed,"event_ids":ids}

    def pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        limit=max(1,min(int(limit),500))
        with self.store.connection() as conn:
            rows=conn.execute(
                """SELECT event_id,provider,canonical_external_ref,message_id,role,ordinal,status,attempt_count,
                next_attempt_at,last_error,created_at,updated_at FROM conversation_ingestion_events
                WHERE status<>'PROCESSED' ORDER BY created_at LIMIT %s""",(limit,)
            ).fetchall()
        return [_normalize(dict(x)) or {} for x in rows]

    def health(self) -> dict[str, Any]:
        with self.store.connection() as conn:
            counts=conn.execute("SELECT status,count(*) AS n FROM conversation_ingestion_events GROUP BY status").fetchall()
            oldest=conn.execute(
                "SELECT min(created_at) AS oldest FROM conversation_ingestion_events WHERE status IN ('PENDING','FAILED','PROCESSING')"
            ).fetchone()
            latest=conn.execute(
                "SELECT max(processed_at) AS latest FROM conversation_ingestion_events WHERE status='PROCESSED'"
            ).fetchone()
        by_status={str(x["status"]):int(x["n"]) for x in counts}
        pending=sum(by_status.get(x,0) for x in ("PENDING","FAILED","PROCESSING"))
        dead=by_status.get("DEAD_LETTER",0)
        oldest_at=oldest.get("oldest") if oldest else None
        lag=(datetime.now(UTC)-oldest_at).total_seconds() if oldest_at else 0.0
        status="OK"
        if dead: status="FAILED"
        elif by_status.get("FAILED",0) or lag>60: status="DEGRADED"
        return {"status":status,"queue":by_status,"pending_total":pending,"dead_letter":dead,
                "oldest_pending_age_seconds":round(max(lag,0.0),3),
                "last_processed_at":latest.get("latest").isoformat() if latest and latest.get("latest") else None,
                "write_through":True,"durable_queue":True,"browser_learning_required":False}
