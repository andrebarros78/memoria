from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .canonical_mutation import CanonicalMutationService
from .client_auth import principal_from_request
from .conversation_ingestion import ConversationIngestionRepository
from .session_rotation_api import _store
from .store import PostgresMemoryStore

router = APIRouter(prefix="/v1/conversation-ingestion", tags=["conversation-ingestion"])


def _ingestor(store: Annotated[PostgresMemoryStore, Depends(_store)]) -> ConversationIngestionRepository:
    return ConversationIngestionRepository(store)


IngestorDep = Annotated[ConversationIngestionRepository, Depends(_ingestor)]


class ConversationTurnRequest(BaseModel):
    provider: str = Field(default="chatgpt", min_length=1, max_length=120)
    external_session_ref: str = Field(min_length=1, max_length=500)
    objective: str = Field(default="Continuous conversation capture", min_length=1, max_length=10000)
    role: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=200000)
    message_id: str = Field(min_length=1, max_length=300)
    ordinal: int = Field(ge=0)
    project_id: str | None = Field(default=None, max_length=200)
    capture_source: str = Field(default="CONVERSATION_RUNTIME", min_length=1, max_length=160)
    process_now: bool = True
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class RetryRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        detail = str(exc)
        return HTTPException(status_code=409 if "already exists" in detail else 422, detail=detail)
    return HTTPException(status_code=500, detail=f"conversation ingestion error: {type(exc).__name__}")


@router.post("/turn", status_code=201)
def ingest_turn(payload: ConversationTurnRequest, request: Request, ingestor: IngestorDep) -> dict[str, Any]:
    try:
        principal = principal_from_request(request)
        return CanonicalMutationService(ingestor.store, actor_id=principal.client_id).run_sanitized(
            "conversation.enqueue", ingestor.enqueue_turn, actor_id=principal.client_id, **payload.model_dump()
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/retry")
def retry_pending(payload: RetryRequest, request: Request, ingestor: IngestorDep) -> dict[str, Any]:
    try:
        principal = principal_from_request(request)
        return CanonicalMutationService(ingestor.store, actor_id=principal.client_id).run_sanitized(
            "conversation.retry", ingestor.retry_pending, actor_id=principal.client_id, limit=payload.limit
        )
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/pending")
def pending(ingestor: IngestorDep, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    try:
        return {"items": ingestor.pending(limit=limit)}
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/health")
def health(ingestor: IngestorDep) -> dict[str, Any]:
    try:
        return ingestor.health()
    except Exception as exc:
        raise _translate(exc) from exc
