from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .canonical_mutation import CanonicalMutationService
from .client_auth import principal_from_request
from .conversation_ingestion import ConversationIngestionRepository
from .request_context import authenticated_store
from .session_rotation import SessionRotationRepository
from .store import PostgresMemoryStore

router = APIRouter(prefix="/v1", tags=["session-rotation"])


def _store(
    request: Request,
    x_memory_tenant: Annotated[str | None, Header(alias="X-Memory-Tenant")] = None,
    x_memory_agent: Annotated[str | None, Header(alias="X-Memory-Agent")] = None,
    x_memory_user: Annotated[str | None, Header(alias="X-Memory-User")] = None,
    x_memory_project: Annotated[str | None, Header(alias="X-Memory-Project")] = None,
    x_memory_team: Annotated[str | None, Header(alias="X-Memory-Team")] = None,
    x_memory_organization: Annotated[str | None, Header(alias="X-Memory-Organization")] = None,
) -> PostgresMemoryStore:
    return authenticated_store(
        request, tenant=x_memory_tenant, agent=x_memory_agent, user=x_memory_user,
        project=x_memory_project, team=x_memory_team, organization=x_memory_organization,
    )


def _repo(store: Annotated[PostgresMemoryStore, Depends(_store)]) -> SessionRotationRepository:
    return SessionRotationRepository(store, initialize=False)


RepoDep = Annotated[SessionRotationRepository, Depends(_repo)]


class ExternalConversationMessage(BaseModel):
    role: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=200000)
    message_id: str | None = Field(default=None, max_length=300)


class ExternalConversationCaptureRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=120)
    external_session_ref: str = Field(min_length=1, max_length=500)
    objective: str = Field(min_length=1, max_length=10000)
    project_id: str | None = Field(default=None, max_length=200)
    capture_source: str = Field(default="EXTERNAL_IMPORT", min_length=1, max_length=160)
    messages: list[ExternalConversationMessage] = Field(min_length=1, max_length=5000)


class ExternalConversationRecoverRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=120)
    external_session_ref: str = Field(min_length=1, max_length=500)


class SessionCreateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    identity: dict[str, Any]
    scope: str = Field(min_length=1, max_length=300)
    objective: str = Field(min_length=1, max_length=10000)
    critical_rules: list[Any] | dict[str, Any] = Field(default_factory=list)
    operational_state: dict[str, Any] = Field(default_factory=dict)
    last_confirmed_action: str | None = Field(default=None, max_length=10000)
    blockers: list[Any] = Field(default_factory=list)
    pending: list[Any] = Field(default_factory=list)
    next_safe_action: str | None = Field(default=None, max_length=10000)
    active_authorizations: list[Any] = Field(default_factory=list)
    required_memory_ids: list[str] = Field(default_factory=list, max_length=1000)


class BindingCreateRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=120)
    external_session_ref: str = Field(min_length=1, max_length=500)


class RotationRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    safe_point: dict[str, Any]
    memory_before_mb: float | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=1000)


class SafePointUpdateRequest(BaseModel):
    safe_point: dict[str, Any]


class PrepareRequest(BaseModel):
    last_event_id: str | None = Field(default=None, max_length=300)


class BindNewRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=120)
    external_session_ref: str = Field(min_length=1, max_length=500)


class ValidateRequest(BaseModel):
    observed_context_sha256: str = Field(min_length=64, max_length=64)
    observed_checkpoint_id: str = Field(min_length=1, max_length=200)
    observed_required_memory_ids: list[str] = Field(default_factory=list, max_length=1000)


class CompleteRequest(BaseModel):
    memory_after_mb: float | None = Field(default=None, ge=0)
    client_old_closed: bool
    client_close_evidence: dict[str, Any] = Field(default_factory=dict)


class AbortRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=f"session rotation error: {type(exc).__name__}")


@router.post("/sessions", status_code=201)
def create_session(payload: SessionCreateRequest, request: Request, repo: RepoDep) -> dict[str, Any]:
    try:
        principal = principal_from_request(request)
        return CanonicalMutationService(repo.store, actor_id=principal.client_id).run_sanitized(
            "session.create", repo.create_session, actor_id=principal.client_id, **payload.model_dump()
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/external-sessions/capture", status_code=201)
def capture_external_session(payload: ExternalConversationCaptureRequest, request: Request, repo: RepoDep) -> dict[str, Any]:
    try:
        principal = principal_from_request(request)
        return CanonicalMutationService(repo.store, actor_id=principal.client_id).run_sanitized(
            "conversation.capture", repo.capture_external_conversation, actor_id=principal.client_id,
            provider=payload.provider, external_session_ref=payload.external_session_ref, objective=payload.objective,
            messages=[item.model_dump() for item in payload.messages], project_id=payload.project_id, capture_source=payload.capture_source,
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/conversations/recover")
def recover_external_conversation(payload: ExternalConversationRecoverRequest, repo: RepoDep) -> dict[str, Any]:
    try:
        return ConversationIngestionRepository(repo.store).resolve(provider=payload.provider, external_session_ref=payload.external_session_ref)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/external-sessions/resolve")
def resolve_external_session(provider: str, external_session_ref: str, repo: RepoDep) -> dict[str, Any]:
    try:
        return ConversationIngestionRepository(repo.store).resolve(provider=provider, external_session_ref=external_session_ref)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/sessions/{session_id}")
def get_session(session_id: str, repo: RepoDep) -> dict[str, Any]:
    try:
        return repo.session(session_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/sessions/{session_id}/resume")
def resume_session(session_id: str, repo: RepoDep) -> dict[str, Any]:
    try:
        return repo.resume_session(session_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/sessions/{session_id}/bindings", status_code=201)
def create_binding(session_id: str, payload: BindingCreateRequest, request: Request, repo: RepoDep) -> dict[str, Any]:
    try:
        principal = principal_from_request(request)
        return CanonicalMutationService(repo.store, actor_id=principal.client_id).run_sanitized(
            "session.bind", repo.create_binding, actor_id=principal.client_id, session_id=session_id,
            provider=payload.provider, external_session_ref=payload.external_session_ref
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/sessions/{session_id}/current-binding")
def current_binding(session_id: str, repo: RepoDep) -> dict[str, Any]:
    try:
        return repo.current_binding(session_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/session-rotations/request", status_code=201)
def request_rotation(payload: RotationRequest, request: Request, repo: RepoDep) -> dict[str, Any]:
    try:
        principal = principal_from_request(request)
        return CanonicalMutationService(repo.store, actor_id=principal.client_id).run_sanitized(
            "rotation.request", repo.request_rotation, actor_id=principal.client_id, **payload.model_dump()
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/session-rotations/{rotation_id}/safe-point")
def update_safe_point(rotation_id: str, payload: SafePointUpdateRequest, request: Request, repo: RepoDep) -> dict[str, Any]:
    try:
        principal = principal_from_request(request)
        return CanonicalMutationService(repo.store, actor_id=principal.client_id).run_sanitized(
            "rotation.safe_point", repo.update_safe_point, rotation_id, actor_id=principal.client_id, safe_point=payload.safe_point
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/session-rotations/{rotation_id}/prepare")
def prepare_rotation(rotation_id: str, payload: PrepareRequest, request: Request, repo: RepoDep) -> dict[str, Any]:
    try:
        principal = principal_from_request(request)
        return CanonicalMutationService(repo.store, actor_id=principal.client_id).run_sanitized(
            "rotation.prepare", repo.prepare_rotation, rotation_id, actor_id=principal.client_id, last_event_id=payload.last_event_id
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/session-rotations/{rotation_id}/bind", status_code=201)
def bind_new(rotation_id: str, payload: BindNewRequest, request: Request, repo: RepoDep) -> dict[str, Any]:
    try:
        principal = principal_from_request(request)
        return CanonicalMutationService(repo.store, actor_id=principal.client_id).run_sanitized(
            "rotation.bind", repo.bind_new_external, rotation_id, actor_id=principal.client_id,
            provider=payload.provider, external_session_ref=payload.external_session_ref
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/context-packs/{context_pack_id}")
def get_context_pack(context_pack_id: str, repo: RepoDep) -> dict[str, Any]:
    try:
        return repo.context_pack(context_pack_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/session-rotations/{rotation_id}/validate")
def validate_rotation(rotation_id: str, payload: ValidateRequest, request: Request, repo: RepoDep) -> dict[str, Any]:
    try:
        principal = principal_from_request(request)
        return CanonicalMutationService(repo.store, actor_id=principal.client_id).run_sanitized(
            "rotation.validate", repo.validate_rotation, rotation_id, actor_id=principal.client_id, **payload.model_dump()
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/session-rotations/{rotation_id}/complete")
def complete_rotation(rotation_id: str, payload: CompleteRequest, request: Request, repo: RepoDep) -> dict[str, Any]:
    try:
        principal = principal_from_request(request)
        return CanonicalMutationService(repo.store, actor_id=principal.client_id).run_sanitized(
            "rotation.complete", repo.complete_rotation, rotation_id, actor_id=principal.client_id, **payload.model_dump()
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/session-rotations/{rotation_id}/abort")
def abort_rotation(rotation_id: str, payload: AbortRequest, request: Request, repo: RepoDep) -> dict[str, Any]:
    try:
        principal = principal_from_request(request)
        return CanonicalMutationService(repo.store, actor_id=principal.client_id).run_sanitized(
            "rotation.abort", repo.abort_rotation, rotation_id, actor_id=principal.client_id, reason=payload.reason
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/session-rotations/{rotation_id}")
def get_rotation(rotation_id: str, repo: RepoDep) -> dict[str, Any]:
    try:
        return repo.rotation(rotation_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/session-rotations-recovery")
def recovery_plan(repo: RepoDep) -> dict[str, Any]:
    try:
        return {"items": repo.recovery_plan()}
    except Exception as exc:
        raise _translate(exc) from exc
