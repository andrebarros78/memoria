from __future__ import annotations

import logging
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .agent_skill_plane import AgentSkillPlane, RegistryError
from .ai_integration_adapter import (
    AI_INTEGRATION_CONTRACT,
    ai_integration_spec,
    ensure_promotable_memory_create,
    normalize_ai_suggestion,
)
from .associative_memory import PostgresAssociationStore
from .canonical_mutation import CanonicalMutationService
from .causal_policy import causal_policy_spec
from .client_auth import (
    authenticate_request,
    issue_browser_session,
    principal_from_request,
)
from .cognitive_activation import CognitiveShadowObserver, PostgresActivationStore
from .consumer_adapter import consumer_adapter_spec
from .context_engine import ContextEngine
from .conversation_ingestion_api import router as conversation_ingestion_router
from .conversational_adapter import conversational_adapter_spec
from .decision_memory import (
    DECISION_RECORD_VERSION,
    DecisionCriticality,
    authority_snapshot,
)
from .domain import OperatorClass
from .economic_memory import (
    EconomicAttributionSource,
    EconomicEntityType,
    EconomicMetricType,
    EconomicStateType,
    economic_spec,
)
from .embedding_provider import FastEmbedProvider
from .erasure_manager import ErasureManager, erasure_spec
from .experience_graph import (
    ExperienceNodeType,
    ExperienceRelationType,
    experience_graph_spec,
)
from .human_governance import HUMAN_GOVERNANCE_CONTRACT, HumanGovernanceManager
from .input_guard import input_guard_spec
from .integrity_governance import IntegrityGovernance
from .lifecycle_manager import LifecycleManager, lifecycle_spec
from .memory_gateway import MemoryGateway
from .memory_scope import MemoryScope, memory_scope_spec
from .ontology import KnowledgeRelationType, KnowledgeType, ontology_spec
from .operational_memory import (
    OperationalProofResult,
    OperationalProofType,
    OperationalStatus,
    operational_memory_spec,
)
from .product_dna import public_identity, response_headers
from .product_universality import product_universality_spec
from .report import render_operational_report
from .request_context import authenticated_store
from .session_rotation_api import router as session_rotation_router
from .store import ConcurrencyConflict, IdempotencyConflict, PostgresMemoryStore
from .temporal import temporal_spec
from .ui_governance import ui_governance_spec
from .v52_operational import build_human_memory_view, build_retrieval_explanation
from .v55_runtime import (
    V55_CONSTRUCTION_RELEASE_CHANNEL,
    V55_CONSTRUCTION_RUNTIME_PROFILE,
    evaluate_conformance,
    v55_runtime_spec,
    validate_profile_selection,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="MEMORIA-PERMANENTE",
    version="0.32.0",
    description="Infraestrutura universal soberana de memoria e contexto V5.5",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(session_rotation_router)
app.include_router(conversation_ingestion_router)


class BrowserSessionRequest(BaseModel):
    ttl_seconds: int = Field(default=600, ge=60, le=900)


class V55ConformanceRequest(BaseModel):
    evidence: dict[str, bool]


class V55ProfileRequest(BaseModel):
    deployment_profile: str = Field(min_length=1, max_length=80)
    capability_profiles: list[str] = Field(default_factory=lambda: ["CORE"], min_length=1, max_length=10)


def _restore_mode_enabled() -> bool:
    return os.getenv("MEMORY_RESTORE_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}

def _restore_traffic_allowed() -> bool:
    if not _restore_mode_enabled():
        return True
    dsn = os.getenv("MEMORY_DSN", "").strip()
    if not dsn:
        return False
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            row = conn.execute("SELECT value FROM schema_meta WHERE key='restore_erasure_replay_status'").fetchone()
            return bool(row and str(row[0]).upper() == "PASS")
    except Exception:
        return False
@app.middleware("http")
async def authenticate_and_attach_product_dna_headers(request: Request, call_next):
    try:
        principal = await authenticate_request(request)
    except HTTPException as exc:
        response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        for name, value in response_headers().items():
            response.headers[name] = value
        return response
    request.state.memory_principal = principal
    restore_exempt = request.url.path in {"/", "/health", "/v1/product-dna", "/v1/product-universality", "/v1/erasure/spec", "/v1/erasure/replay"}
    if _restore_mode_enabled() and not restore_exempt and not _restore_traffic_allowed():
        response = JSONResponse(status_code=503, content={"detail": "RESTORE_BLOCKED_PENDING_ERASURE_REPLAY"})
    else:
        response = await call_next(request)
    for name, value in response_headers().items():
        response.headers[name] = value
    return response


@app.get("/v1/product-dna")
def product_dna_identity() -> dict[str, Any]:
    return public_identity()


@app.get("/v1/product-universality")
def product_universality_identity() -> dict[str, Any]:
    return product_universality_spec()


@app.get("/v1/v5.5/runtime")
def v55_runtime_identity() -> dict[str, Any]:
    return v55_runtime_spec()


@app.get("/v1/v5.5/consumer-adapter")
def v55_consumer_adapter_identity() -> dict[str, Any]:
    return consumer_adapter_spec()


@app.get("/v1/v5.5/conversational-adapter")
def v55_conversational_adapter_identity() -> dict[str, Any]:
    return conversational_adapter_spec()


@app.post("/v1/v5.5/profiles/validate")
def v55_validate_profiles(payload: V55ProfileRequest) -> dict[str, Any]:
    try:
        return validate_profile_selection(payload.deployment_profile, payload.capability_profiles)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/v5.5/conformance/evaluate")
def v55_evaluate_conformance(payload: V55ConformanceRequest) -> dict[str, Any]:
    return evaluate_conformance(payload.evidence).as_dict()


@app.post("/v1/auth/browser-sessions")
def create_browser_session(payload: BrowserSessionRequest, request: Request) -> dict[str, Any]:
    principal = principal_from_request(request)
    return issue_browser_session(principal, payload.ttl_seconds)


_STATIC = Path(__file__).resolve().parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


def get_store(
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


@lru_cache(maxsize=1)
def get_embedding_provider() -> FastEmbedProvider | None:
    enabled = os.getenv("MEMORY_SEMANTIC_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
    if not enabled:
        return None
    model_name = os.getenv(
        "MEMORY_EMBEDDING_MODEL",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ).strip()
    cache_dir = os.getenv("MEMORY_EMBEDDING_CACHE", "").strip() or str(
        Path(__file__).resolve().parents[2] / "runtime" / "models" / "fastembed"
    )
    identity = os.getenv("MEMORY_EMBEDDING_IDENTITY", "").strip() or model_name
    return FastEmbedProvider(model_name=model_name, cache_dir=cache_dir, threads=2, identity=identity)


def _feature_enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def get_cognitive_shadow_observer(store: PostgresMemoryStore) -> CognitiveShadowObserver | None:
    activation = _feature_enabled("COGNITIVE_ACTIVATION")
    priming = _feature_enabled("COGNITIVE_PRIMING")
    salience = _feature_enabled("COGNITIVE_SALIENCE")
    association = _feature_enabled("COGNITIVE_ASSOCIATION")
    if not any((activation, priming, salience, association)):
        return None
    return CognitiveShadowObserver(
        PostgresActivationStore(store),
        activation_enabled=activation,
        priming_enabled=priming,
        salience_enabled=salience,
        association_enabled=association,
        association_store=PostgresAssociationStore(store) if association else None,
    )


def get_gateway(store: Annotated[PostgresMemoryStore, Depends(get_store)]) -> MemoryGateway:
    semantic_min_similarity = float(os.getenv("MEMORY_SEMANTIC_MIN_SIMILARITY", "0.40"))
    return MemoryGateway(
        ContextEngine(
            store,
            get_embedding_provider(),
            semantic_min_similarity=semantic_min_similarity,
            cognitive_observer=get_cognitive_shadow_observer(store),
        )
    )


StoreDep = Annotated[PostgresMemoryStore, Depends(get_store)]
GatewayDep = Annotated[MemoryGateway, Depends(get_gateway)]


class AIIntegrationSuggestionRequest(BaseModel):
    external_system_id: str = Field(min_length=1, max_length=120)
    external_trace_id: str = Field(min_length=1, max_length=240)
    suggestion_type: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any]
    target_item_id: str | None = Field(default=None, max_length=160)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = Field(default="", max_length=4000)
    model_ref: str | None = Field(default=None, max_length=240)


class AIIntegrationDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(ACCEPTED|REJECTED)$")
    rationale: str = Field(default="", max_length=4000)
    evidence: dict[str, Any] = Field(default_factory=dict)


class AIIntegrationPromoteRequest(BaseModel):
    rationale: str = Field(default="", max_length=4000)
    evidence: dict[str, Any] = Field(default_factory=dict)


class ClassificationRequest(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=500)
    operator_class: OperatorClass
    changed_by: str = Field(min_length=1, max_length=120)


class RememberRequest(BaseModel):
    namespace: str = Field(min_length=1, max_length=120)
    memory_key: str = Field(min_length=1, max_length=300)
    category: KnowledgeType = KnowledgeType.FACT
    content: dict[str, Any]
    content_text: str = Field(min_length=1, max_length=200000)
    provenance: dict[str, Any]
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(min_length=1, max_length=160)
    source_version: str | None = Field(default=None, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=100)
    changed_by: str = Field(default="api", min_length=1, max_length=120)
    memory_scope: MemoryScope = MemoryScope.GLOBAL_USER
    memory_scope_ref: str | None = Field(default=None, max_length=240)
    sharing_scope: str = Field(default="SYSTEM_SHARED", min_length=1, max_length=40)
    owner_user_id: str | None = Field(default=None, max_length=160)
    owner_agent_id: str | None = Field(default=None, max_length=160)
    project_id: str | None = Field(default=None, max_length=160)
    team_id: str | None = Field(default=None, max_length=160)
    organization_id: str | None = Field(default=None, max_length=160)
    validation_status: str = Field(default="UNVALIDATED", min_length=1, max_length=40)
    governor_eligible: bool = False
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class KnowledgeRelationRequest(BaseModel):
    from_item_id: str = Field(min_length=1, max_length=240)
    relation_type: KnowledgeRelationType
    to_item_id: str = Field(min_length=1, max_length=240)
    provenance: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class OntologyTransitionRequest(BaseModel):
    to_category: KnowledgeType
    reason: str = Field(min_length=1, max_length=500)
    evidence: dict[str, Any] = Field(default_factory=dict)




class CausalAssessmentRequest(BaseModel):
    hypothesis: dict[str, Any]
    intervention: dict[str, Any]
    comparator: dict[str, Any]
    confounders: list[Any]
    confounder_control: dict[str, Any]
    mechanism: dict[str, Any]
    counterfactual: dict[str, Any]
    attribution_confidence: float = Field(ge=0.0, le=1.0)
    sample_size: int = Field(ge=1)
    repetition_count: int = Field(ge=1)
    evidence: dict[str, Any]
    occurred_at: datetime | None = None


class CausalPromotionRequest(BaseModel):
    assessment_id: str = Field(min_length=1, max_length=240)
    reason: str = Field(min_length=1, max_length=500)


class DecisionEvidenceRefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str = Field(min_length=1, max_length=240)
    version_id: str | None = Field(default=None, max_length=240)
    role: str = Field(default="EVIDENCE", min_length=1, max_length=80)


class SovereignDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mission_id: str = Field(min_length=1, max_length=240)
    criticality: DecisionCriticality = DecisionCriticality.NORMAL
    objective: str = Field(min_length=1, max_length=4000)
    context: dict[str, Any] = Field(default_factory=dict)
    alternatives: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=1, max_length=12000)
    action: dict[str, Any]
    expected_outcome: dict[str, Any]
    proof: dict[str, Any]
    evidence_refs: list[DecisionEvidenceRefRequest] = Field(default_factory=list, max_length=100)
    occurred_at: datetime | None = None


class SovereignDecisionOutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    success: bool
    actual_outcome: dict[str, Any]
    proof: dict[str, Any]
    occurred_at: datetime | None = None


class SovereignDecisionReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class RevisionRequest(BaseModel):
    content: dict[str, Any]
    content_text: str = Field(min_length=1, max_length=200000)
    provenance: dict[str, Any]
    confidence: float = Field(ge=0.0, le=1.0)
    source: str = Field(min_length=1, max_length=160)
    source_version: str | None = Field(default=None, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=100)
    changed_by: str = Field(default="api", min_length=1, max_length=120)
    expected_version: int | None = Field(default=None, ge=1)
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class ValidationRequest(BaseModel):
    expected_version: int = Field(ge=1)
    expected_content_sha256: str = Field(min_length=64, max_length=64)
    status: str = Field(pattern="^(VALIDATED|REJECTED)$")
    governor_eligible: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)


class ApplicationRequest(BaseModel):
    action_ref: str = Field(min_length=1, max_length=300)
    mission_id: str | None = Field(default=None, max_length=240)
    decision_id: str | None = Field(default=None, max_length=240)
    context: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class OutcomeRequest(BaseModel):
    success: bool
    outcome_type: str = Field(min_length=1, max_length=120)
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)
    confidence_delta: float | None = Field(default=None, ge=-1.0, le=1.0, description="Deprecated: accepted for compatibility but ignored by LearningPolicyEngine")
    evidence: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class ExperienceGraphNodeRequest(BaseModel):
    node_type: ExperienceNodeType
    entity_ref: str = Field(min_length=1, max_length=300)
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    memory_item_id: str | None = Field(default=None, max_length=240)
    memory_version_id: str | None = Field(default=None, max_length=240)
    occurred_at: datetime | None = None


class ExperienceGraphEdgeRequest(BaseModel):
    from_node_id: str = Field(min_length=1, max_length=240)
    relation_type: ExperienceRelationType
    to_node_id: str = Field(min_length=1, max_length=240)
    evidence: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class EconomicEntityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: EconomicEntityType
    external_ref: str = Field(min_length=1, max_length=300)
    parent_entity_id: str | None = Field(default=None, max_length=240)
    attributes: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class EconomicStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    economic_entity_id: str = Field(min_length=1, max_length=240)
    mission_id: str | None = Field(default=None, max_length=240)
    state_type: EconomicStateType
    value: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=40)
    currency: str | None = Field(default=None, max_length=3)
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class EconomicAttributionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_kind: EconomicAttributionSource
    source_id: str = Field(min_length=1, max_length=240)
    weight: str = Field(min_length=1, max_length=80)
    rationale: str = Field(default="", max_length=4000)
    evidence: dict[str, Any] = Field(default_factory=dict)


class EconomicResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mission_id: str = Field(min_length=1, max_length=240)
    economic_entity_id: str | None = Field(default=None, max_length=240)
    metric_type: EconomicMetricType
    value: str = Field(min_length=1, max_length=120)
    unit: str = Field(min_length=1, max_length=40)
    currency: str | None = Field(default=None, max_length=3)
    experience_result_node_id: str | None = Field(default=None, max_length=240)
    proof: dict[str, Any]
    attributions: list[EconomicAttributionRequest] = Field(min_length=1, max_length=100)
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class OperationalCompetencyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    competency_key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=8000)
    domain: str = Field(default="GENERAL", min_length=1, max_length=160)
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class OperationalSkillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    competency_id: str = Field(min_length=1, max_length=240)
    skill_key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=8000)
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class OperationalSkillVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: str = Field(min_length=1, max_length=240)
    version_label: str = Field(min_length=1, max_length=120)
    implementation_version: str = Field(min_length=1, max_length=120)
    implementation_sha256: str = Field(min_length=64, max_length=64, pattern="^[0-9a-fA-F]{64}$")
    contract: dict[str, Any]
    supersedes_skill_version_id: str | None = Field(default=None, max_length=240)
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class OperationalCapabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability_key: str = Field(min_length=1, max_length=160)
    contract: dict[str, Any]
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class OperationalProofRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proof_type: OperationalProofType
    result: OperationalProofResult
    artifact_ref: str = Field(min_length=1, max_length=500)
    artifact_sha256: str = Field(min_length=64, max_length=64, pattern="^[0-9a-fA-F]{64}$")
    evidence: dict[str, Any]
    executed_at: datetime | None = None
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class OperationalStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: OperationalStatus
    reason: str = Field(min_length=1, max_length=4000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class LeaseAcquireRequest(BaseModel):
    ttl_seconds: int = Field(default=30, ge=1, le=3600)


class LeaseReleaseRequest(BaseModel):
    fencing_token: int = Field(ge=1)


class ContextRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    namespaces: list[str] = Field(min_length=1, max_length=50)
    limit: int = Field(default=8, ge=1, le=100)
    mission_id: str | None = Field(default=None, max_length=240)
    session_id: str | None = Field(default=None, max_length=240)
    valid_at: datetime | None = None
    known_at: datetime | None = None


class CheckpointRequest(BaseModel):
    namespace: str = Field(min_length=1, max_length=120)
    mission_id: str = Field(min_length=1, max_length=240)
    step_index: int = Field(ge=0)
    state: dict[str, Any]
    checkpoint_id: str | None = Field(default=None, max_length=240)
    project_id: str | None = Field(default=None, max_length=160)
    occurred_at: datetime | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


def health() -> dict[str, object]:
    """Internal health contract used by tests and operational code."""
    return _health_details()


@app.get("/health")
def public_health() -> dict[str, object]:
    details = health()
    return {
        "status": details["status"],
        "service": details["service"],
        "runtime_profile": details["runtime_profile"],
        "release_channel": details["release_channel"],
    }


def _health_details() -> dict[str, object]:
    identity = public_identity()
    runtime_profile = os.getenv("MEMORY_RUNTIME_PROFILE", V55_CONSTRUCTION_RUNTIME_PROFILE)
    agent_skill_required = os.getenv("MEMORY_REQUIRE_AGENT_SKILL_PLANE", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    try:
        agent_skill_health = AgentSkillPlane().health()
    except RegistryError as exc:
        missing_optional_registry = (
            "project root with .agents was not found" in str(exc) and not agent_skill_required
        )
        if missing_optional_registry:
            logger.info("agent/skill plane not installed; continuing because it is optional")
            agent_skill_health = {
                "status": "NOT_CONFIGURED",
                "required": False,
                "agents_total": 0,
                "agents_loaded": 0,
                "skills_total": 0,
                "skills_callable": 0,
                "errors": [],
            }
        else:
            logger.exception("agent/skill plane health failed")
            agent_skill_health = {
                "status": "UNHEALTHY",
                "required": agent_skill_required,
                "agents_total": 0,
                "agents_loaded": 0,
                "skills_total": 0,
                "skills_callable": 0,
                "errors": [f"{type(exc).__name__}:{exc}"],
            }
    except Exception as exc:
        logger.exception("agent/skill plane health failed")
        agent_skill_health = {
            "status": "UNHEALTHY",
            "required": agent_skill_required,
            "agents_total": 0,
            "agents_loaded": 0,
            "skills_total": 0,
            "skills_callable": 0,
            "errors": [f"{type(exc).__name__}:{exc}"],
        }

    dsn = os.getenv("MEMORY_DATABASE_URL", "").strip() or os.getenv("MEMORY_DSN", "").strip()
    database_health: dict[str, object] = {"status": "NOT_CONFIGURED"}
    if dsn:
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                row = conn.execute("SELECT current_user,current_setting('server_version')").fetchone()
            database_health = {
                "status": "READY",
                "role": str(row[0]) if row else "UNKNOWN",
                "postgresql": str(row[1]) if row else "UNKNOWN",
            }
        except Exception as exc:
            logger.exception("database health failed")
            database_health = {"status": "UNHEALTHY", "error": type(exc).__name__}

    database_required = runtime_profile in {"V5.3-PRIMARY", "V5.5-PRIMARY"}
    v55 = v55_runtime_spec()
    v55_required = runtime_profile == "V5.5-PRIMARY"
    v55_ok = (
        v55["closure_points_count"] == 8
        and v55["all_official_adapters_available"] is True
        and int(v55["security_layer_count"]) >= 10
        and v55["direct_external_database_access"] is False
    )
    agent_skill_ok = agent_skill_health.get("status") == "HEALTHY" or (
        agent_skill_health.get("status") == "NOT_CONFIGURED" and not agent_skill_required
    )
    dependencies_ok = (
        agent_skill_ok
        and (database_health.get("status") == "READY" or not database_required)
        and (v55_ok or not v55_required)
    )
    return {
        "status": "ok" if dependencies_ok else "degraded",
        "service": "MEMORIA-PERMANENTE",
        "version": "0.32.0",
        "purge_direct_enabled": False,
        "product_id": identity["product_id"],
        "dna_sha256": identity["dna_sha256"],
        "trust_class": identity["trust_class"],
        "runtime_profile": runtime_profile,
        "release_channel": os.getenv("MEMORY_RELEASE_CHANNEL", V55_CONSTRUCTION_RELEASE_CHANNEL),
        "ai_integration_adapter": AI_INTEGRATION_CONTRACT,
        "agent_skill_plane": agent_skill_health,
        "database": database_health,
        "v55": {
            "required": v55_required,
            "ready": v55_ok,
            "contract": v55["contract"],
            "closure_points_count": v55["closure_points_count"],
            "security_layer_count": v55["security_layer_count"],
            "all_official_adapters_available": v55["all_official_adapters_available"],
        },
    }


@app.get("/v1/health/details")
def health_details() -> dict[str, object]:
    return _health_details()


@app.get("/", response_class=HTMLResponse)
def panel() -> HTMLResponse:
    index = _STATIC / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>MEMORIA-PERMANENTE</h1><p>Painel ainda nÃƒÆ’Ã‚Â£o empacotado.</p>")
    return HTMLResponse(index.read_text(encoding="utf-8"))


@app.get("/v1/dashboard/summary")
def dashboard_summary(store: StoreDep) -> dict[str, object]:
    return store.summary()


@app.get("/v1/dashboard/human-memory")
def dashboard_human_memory(store: StoreDep, limit: int = Query(default=80, ge=1, le=300)) -> dict[str, object]:
    return build_human_memory_view(
        store.summary(),
        store.list_memories(limit=limit),
        latest_trace=store.latest_retrieval_trace(),
        observability=store.v52_observability(),
    )


@app.get("/v1/observability/v52")
def observability_v52(store: StoreDep) -> dict[str, object]:
    return store.v52_observability()


@app.get("/v1/ai-integration/spec")
def get_ai_integration_spec() -> dict[str, object]:
    return ai_integration_spec()


@app.post("/v1/ai-integration/suggestions", status_code=202)
def record_ai_integration_suggestion(request: Request, payload: AIIntegrationSuggestionRequest, store: StoreDep) -> dict[str, object]:
    principal = principal_from_request(request)
    try:
        normalized = normalize_ai_suggestion(external_system_id=payload.external_system_id, external_trace_id=payload.external_trace_id, suggestion_type=payload.suggestion_type, payload=payload.payload, target_item_id=payload.target_item_id, confidence=payload.confidence, rationale=payload.rationale, model_ref=payload.model_ref)
        mutations = CanonicalMutationService(store, actor_id=principal.client_id)
        return mutations.run_sanitized("ai.integration.suggestion.record", store.record_ai_integration_suggestion, actor_id=principal.client_id, external_system_id=payload.external_system_id, external_trace_id=payload.external_trace_id, suggestion_type=normalized["suggestion_type"], target_item_id=payload.target_item_id, raw_payload=payload.payload, normalized_payload=normalized, risk_level=normalized["risk"]["level"], created_by=principal.client_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/ai-integration/suggestions")
def list_ai_integration_suggestions(store: StoreDep, suggestion_type: str | None = Query(default=None, max_length=80), limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    return {"contract": AI_INTEGRATION_CONTRACT, "items": store.list_ai_integration_suggestions(suggestion_type=suggestion_type, limit=limit)}


@app.get("/v1/ai-integration/suggestions/{suggestion_id}")
def get_ai_integration_suggestion(suggestion_id: str, store: StoreDep) -> dict[str, object]:
    try:
        return {"contract": AI_INTEGRATION_CONTRACT, "item": store.get_ai_integration_suggestion(suggestion_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"AI suggestion not found: {suggestion_id}") from exc


@app.post("/v1/ai-integration/suggestions/{suggestion_id}/decisions", status_code=201)
def decide_ai_integration_suggestion(suggestion_id: str, payload: AIIntegrationDecisionRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal = principal_from_request(request)
    try:
        mutations = CanonicalMutationService(store, actor_id=principal.client_id)
        return mutations.run_sanitized("ai.integration.decision.record", store.record_ai_integration_decision, actor_id=principal.client_id, suggestion_id=suggestion_id, decision=payload.decision, rationale=payload.rationale, evidence=payload.evidence, promoted_item_id=None, created_by=principal.client_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"AI suggestion not found: {suggestion_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/ai-integration/suggestions/{suggestion_id}/promote", status_code=201)
def promote_ai_integration_suggestion(suggestion_id: str, payload: AIIntegrationPromoteRequest, request: Request, gateway: GatewayDep) -> dict[str, object]:
    principal = principal_from_request(request)
    store = gateway.context_engine.store
    try:
        suggestion = store.get_ai_integration_suggestion(suggestion_id)
        latest = store.latest_ai_integration_decision(suggestion_id)
        if not latest or str(latest.get("decision")) != "ACCEPTED":
            raise HTTPException(status_code=409, detail="AI suggestion must be accepted before promotion")
        normalized = dict(suggestion.get("normalized_payload") or {})
        memory_payload = ensure_promotable_memory_create(normalized)
        mutations = CanonicalMutationService(store, actor_id=principal.client_id)
        item_id = mutations.remember_internal(actor_id=principal.client_id, source=f"ai-integration:{suggestion['external_system_id']}", provenance={"contract": AI_INTEGRATION_CONTRACT, "external_trace_id": suggestion["external_trace_id"], "suggestion_id": suggestion_id, "policy": "AI_SUGGESTS_MEMORY_GOVERNS", "promotion_evidence": payload.evidence, "promotion_rationale": payload.rationale}, trusted=False, **memory_payload)
        decision = mutations.run_sanitized("ai.integration.decision.record", store.record_ai_integration_decision, actor_id=principal.client_id, suggestion_id=suggestion_id, decision="PROMOTED", rationale=payload.rationale, evidence={**payload.evidence, "promoted_item_id": item_id}, promoted_item_id=item_id, created_by=principal.client_id)
        return {"contract": AI_INTEGRATION_CONTRACT, "suggestion_id": suggestion_id, "promoted_item_id": item_id, "decision": decision}
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"AI suggestion not found: {suggestion_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/memories")
def list_memories(
    store: StoreDep,
    q: str | None = Query(default=None, max_length=500),
    operator_class: OperatorClass | None = None,
    memory_scope: MemoryScope | None = None,
    memory_scope_ref: str | None = Query(default=None, max_length=240),
    valid_at: datetime | None = Query(default=None),
    known_at: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, object]:
    try:
        return {"items": store.list_memories(query=q, operator_class=operator_class.value if operator_class else None, memory_scope=memory_scope.value if memory_scope else None, memory_scope_ref=memory_scope_ref, valid_at=valid_at, known_at=known_at, limit=limit)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/input-guard/spec")
def get_input_guard_spec() -> dict[str, object]:
    return input_guard_spec()


@app.get("/v1/memory-scopes")
def get_memory_scopes() -> dict[str, object]:
    return memory_scope_spec()


@app.get("/v1/temporal-spec")
def get_temporal_spec() -> dict[str, object]:
    return temporal_spec()


@app.get("/v1/ontology")
def get_ontology() -> dict[str, object]:
    return ontology_spec()


@app.post("/v1/knowledge-relations", status_code=201)
def create_knowledge_relation(payload: KnowledgeRelationRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal = principal_from_request(request)
    mutations = CanonicalMutationService(store, actor_id=principal.client_id)
    try:
        return mutations.run_sanitized(
            "ontology.relation", store.create_knowledge_relation, actor_id=principal.client_id,
            from_item_id=payload.from_item_id, relation_type=payload.relation_type.value,
            to_item_id=payload.to_item_id, provenance=payload.provenance, confidence=payload.confidence,
            created_by=principal.client_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"memory not found: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/v1/memories/{item_id}/knowledge-relations")
def list_knowledge_relations(item_id: str, store: StoreDep, status: str | None = Query(default=None, pattern="^(ACTIVE|STALE)$"), limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    return {"item_id":item_id,"relations":store.list_knowledge_relations(item_id,status=status,limit=limit)}


@app.post("/v1/memories/{item_id}/ontology-transition")
def transition_knowledge_type(item_id: str, payload: OntologyTransitionRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal = principal_from_request(request)
    mutations = CanonicalMutationService(store, actor_id=principal.client_id)
    try:
        return mutations.run_sanitized(
            "ontology.transition", store.transition_knowledge_type, actor_id=principal.client_id,
            item_id=item_id, to_category=payload.to_category.value, reason=payload.reason, evidence=payload.evidence,
            actor_id_value=principal.client_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"memory not found: {item_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc




@app.get("/v1/causal-policy")
def get_causal_policy() -> dict[str, object]:
    return causal_policy_spec()


@app.post("/v1/memories/{item_id}/causal-assessments", status_code=201)
def create_causal_assessment(item_id: str, payload: CausalAssessmentRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    mutations=CanonicalMutationService(store,actor_id=principal.client_id)
    try:
        return mutations.run_sanitized(
            "causal.assessment",store.create_causal_assessment,actor_id=principal.client_id,item_id=item_id,
            hypothesis=payload.hypothesis,intervention=payload.intervention,comparator=payload.comparator,
            confounders=payload.confounders,confounder_control=payload.confounder_control,mechanism=payload.mechanism,
            counterfactual=payload.counterfactual,attribution_confidence=payload.attribution_confidence,
            sample_size=payload.sample_size,repetition_count=payload.repetition_count,evidence=payload.evidence,
            created_by=principal.client_id,occurred_at=payload.occurred_at,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404,detail=f"memory not found: {item_id}") from exc
    except (ValueError,ConcurrencyConflict) as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.get("/v1/memories/{item_id}/causal-assessments")
def get_causal_assessments(item_id: str, store: StoreDep, limit: int = Query(default=100,ge=1,le=500)) -> dict[str, object]:
    return {"item_id":item_id,"assessments":store.list_causal_assessments(item_id,limit=limit)}


@app.post("/v1/memories/{item_id}/causal-promotion")
def promote_causal_memory(item_id: str, payload: CausalPromotionRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    mutations=CanonicalMutationService(store,actor_id=principal.client_id)
    try:
        return mutations.run_sanitized(
            "causal.promote",store.promote_cause,actor_id=principal.client_id,item_id=item_id,
            assessment_id=payload.assessment_id,reason=payload.reason,actor_id_value=principal.client_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404,detail=f"causal assessment or memory not found: {exc.args[0]}") from exc
    except ConcurrencyConflict as exc:
        raise HTTPException(status_code=409,detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.get("/v1/decision-record-spec")
def decision_record_spec() -> dict[str, object]:
    return {
        "version": DECISION_RECORD_VERSION,
        "criticality": [x.value for x in DecisionCriticality],
        "required_core_fields": ["mission_id","objective","context","alternatives","rationale","authority","action","expected_outcome","proof"],
        "authority": "DERIVED_FROM_AUTHENTICATED_CLIENT",
        "evidence_binding": "ITEM_VERSION_SHA256_SNAPSHOT",
        "replay_mode": "MATERIALIZED_NO_SIDE_EFFECT",
    }


@app.post("/v1/decisions", status_code=201)
def create_sovereign_decision(payload: SovereignDecisionRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    mutations=CanonicalMutationService(store,actor_id=principal.client_id)
    try:
        return mutations.run_sanitized(
            "decision.create",store.create_sovereign_decision,actor_id=principal.client_id,
            mission_id=payload.mission_id,criticality=payload.criticality.value,objective=payload.objective,
            context=payload.context,alternatives=payload.alternatives,rationale=payload.rationale,
            authority=authority_snapshot(principal,store.tenant_id),action=payload.action,
            expected_outcome=payload.expected_outcome,proof=payload.proof,
            evidence_refs=[x.model_dump() for x in payload.evidence_refs],created_by=principal.client_id,
            occurred_at=payload.occurred_at,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404,detail=f"decision mission or evidence not found: {exc.args[0]}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403,detail=str(exc)) from exc
    except ConcurrencyConflict as exc:
        raise HTTPException(status_code=409,detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.get("/v1/decisions/{decision_id}")
def get_sovereign_decision(decision_id: str, store: StoreDep) -> dict[str, object]:
    try:
        return store.get_sovereign_decision(decision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404,detail=f"decision not found: {decision_id}") from exc


@app.get("/v1/decisions/{decision_id}/replay-package")
def get_sovereign_decision_replay_package(decision_id: str, store: StoreDep) -> dict[str, object]:
    try:
        return store.get_sovereign_decision(decision_id)["replay_package"]
    except KeyError as exc:
        raise HTTPException(status_code=404,detail=f"decision not found: {decision_id}") from exc


@app.post("/v1/decisions/{decision_id}/outcomes", status_code=201)
def record_sovereign_decision_outcome(decision_id: str, payload: SovereignDecisionOutcomeRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    mutations=CanonicalMutationService(store,actor_id=principal.client_id)
    try:
        return mutations.run_sanitized(
            "decision.outcome",store.record_sovereign_decision_outcome,actor_id=principal.client_id,
            decision_id=decision_id,success=payload.success,actual_outcome=payload.actual_outcome,
            proof=payload.proof,recorded_by=principal.client_id,occurred_at=payload.occurred_at,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404,detail=f"decision not found: {decision_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.post("/v1/decisions/{decision_id}/replays", status_code=201)
def materialize_sovereign_decision_replay(decision_id: str, payload: SovereignDecisionReplayRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    mutations=CanonicalMutationService(store,actor_id=principal.client_id)
    try:
        return mutations.run_sanitized(
            "decision.replay",store.materialize_sovereign_decision_replay,actor_id=principal.client_id,
            decision_id=decision_id,requested_by=principal.client_id,reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404,detail=f"decision not found: {decision_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.post("/v1/memories", status_code=201)
def remember_memory(
    request: Request,
    payload: RememberRequest,
    gateway: GatewayDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, str]:
    if payload.validation_status.strip().upper() != "UNVALIDATED" or payload.governor_eligible:
        raise HTTPException(status_code=403, detail="validation and governor eligibility require the dedicated validation capability")
    principal = principal_from_request(request)
    mutations = CanonicalMutationService(gateway.context_engine.store, actor_id=principal.client_id)
    try:
        item_id = mutations.remember_authenticated(
            principal=principal, asserted_source=payload.source, asserted_provenance=payload.provenance,
            namespace=payload.namespace.strip().upper(), memory_key=payload.memory_key,
            category=payload.category.value, content=payload.content, content_text=payload.content_text,
            memory_scope=payload.memory_scope.value, memory_scope_ref=payload.memory_scope_ref,
            confidence=payload.confidence, source_version=payload.source_version, tags=payload.tags,
            idempotency_key=idempotency_key, sharing_scope=payload.sharing_scope,
            owner_user_id=payload.owner_user_id, owner_agent_id=payload.owner_agent_id,
            project_id=payload.project_id, team_id=payload.team_id, organization_id=payload.organization_id,
            occurred_at=payload.occurred_at, observed_at=payload.observed_at,
            valid_from=payload.valid_from, valid_to=payload.valid_to,
        )
        observer = gateway.context_engine.cognitive_observer
        if observer is not None:
            try:
                raw_signals = payload.provenance.get("salience_signals") if isinstance(payload.provenance, dict) else None
                evidence_refs = payload.provenance.get("evidence_refs", ()) if isinstance(payload.provenance, dict) else ()
                submit_capture = getattr(observer, "submit_capture", None)
                kwargs = {
                    "memory_id": item_id,
                    "base_strength": payload.confidence,
                    "salience_signals": raw_signals if isinstance(raw_signals, dict) else None,
                    "source_trust": 0.5,
                    "evidence_refs": tuple(str(ref) for ref in evidence_refs if str(ref).strip()),
                }
                if callable(submit_capture):
                    submit_capture(**kwargs)
                else:
                    observer.observe_capture(**kwargs)
            except Exception:
                observer.record_failure()
                logger.warning("cognitive capture shadow failed; canonical capture remains authoritative", exc_info=True)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"item_id": item_id, "status": "CREATED_OR_REPLAYED"}


@app.get("/v1/memories/{item_id}/versions")
def memory_versions(item_id: str, store: StoreDep) -> dict[str, object]:
    return {"item_id": item_id, "versions": store.list_versions(item_id)}


@app.post("/v1/memories/{item_id}/versions", status_code=201)
def revise_memory(
    request: Request,
    item_id: str,
    payload: RevisionRequest,
    gateway: GatewayDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    principal = principal_from_request(request)
    mutations = CanonicalMutationService(gateway.context_engine.store, actor_id=principal.client_id)
    try:
        return mutations.revise_authenticated(
            item_id, principal=principal, asserted_source=payload.source, asserted_provenance=payload.provenance,
            content=payload.content, content_text=payload.content_text, confidence=payload.confidence,
            source_version=payload.source_version, tags=payload.tags, idempotency_key=idempotency_key,
            expected_version=payload.expected_version,
            occurred_at=payload.occurred_at, observed_at=payload.observed_at,
            valid_from=payload.valid_from, valid_to=payload.valid_to,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"memory not found: {item_id}") from exc
    except (IdempotencyConflict, ConcurrencyConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/memories/{item_id}/validation")
def validate_memory(item_id: str, payload: ValidationRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal = principal_from_request(request)
    mutations = CanonicalMutationService(store, actor_id=principal.client_id)
    try:
        return mutations.validate_current_version(
            item_id, actor_id=principal.client_id, expected_version=payload.expected_version,
            expected_content_sha256=payload.expected_content_sha256.lower(), status=payload.status,
            governor_eligible=payload.governor_eligible, validator_client_id=principal.client_id, evidence=payload.evidence,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"memory not found: {item_id}") from exc
    except ConcurrencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/v1/economic-memory/spec")
def get_economic_memory_spec() -> dict[str, object]:
    return economic_spec()


@app.post("/v1/economy/entities", status_code=201)
def create_economic_entity(payload: EconomicEntityRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    try:
        return CanonicalMutationService(store,actor_id=principal.client_id).run_sanitized(
            "economic.entity",store.create_economic_entity,actor_id=principal.client_id,
            entity_type=payload.entity_type.value,external_ref=payload.external_ref,parent_entity_id=payload.parent_entity_id,
            attributes=payload.attributes,created_by=principal.client_id,occurred_at=payload.occurred_at,
            observed_at=payload.observed_at,valid_from=payload.valid_from,valid_to=payload.valid_to,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404,detail=f"economic parent not found: {exc.args[0]}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403,detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc
    except Exception as exc:
        if "unique" in str(exc).lower(): raise HTTPException(status_code=409,detail="economic entity already exists") from exc
        raise


@app.post("/v1/economy/states", status_code=201)
def record_economic_state(payload: EconomicStateRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    try:
        return CanonicalMutationService(store,actor_id=principal.client_id).run_sanitized(
            "economic.state",store.record_economic_state,actor_id=principal.client_id,
            economic_entity_id=payload.economic_entity_id,mission_id=payload.mission_id,state_type=payload.state_type.value,
            value=payload.value,unit=payload.unit,currency=payload.currency,metadata=payload.metadata,created_by=principal.client_id,
            occurred_at=payload.occurred_at,observed_at=payload.observed_at,valid_from=payload.valid_from,valid_to=payload.valid_to,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404,detail=f"economic entity not found: {exc.args[0]}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403,detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.post("/v1/economy/results", status_code=201)
def record_economic_result(payload: EconomicResultRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    try:
        return CanonicalMutationService(store,actor_id=principal.client_id).run_sanitized(
            "economic.result",store.record_economic_result,actor_id=principal.client_id,
            mission_id=payload.mission_id,economic_entity_id=payload.economic_entity_id,metric_type=payload.metric_type.value,
            value=payload.value,unit=payload.unit,currency=payload.currency,experience_result_node_id=payload.experience_result_node_id,
            proof=payload.proof,attributions=[x.model_dump(mode="json") for x in payload.attributions],created_by=principal.client_id,
            occurred_at=payload.occurred_at,observed_at=payload.observed_at,valid_from=payload.valid_from,valid_to=payload.valid_to,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404,detail=f"economic attribution source not found: {exc.args[0]}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403,detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.get("/v1/economy/results/{economic_result_id}")
def get_economic_result(economic_result_id: str, store: StoreDep) -> dict[str, object]:
    try:
        return store.get_economic_result(economic_result_id)
    except KeyError as exc:
        raise HTTPException(status_code=404,detail=f"economic result not found: {economic_result_id}") from exc


@app.get("/v1/economy/history")
def get_economic_history(store: StoreDep, economic_entity_id: str | None = Query(default=None,max_length=240),
    mission_id: str | None = Query(default=None,max_length=240), valid_at: datetime | None = Query(default=None),
    known_at: datetime | None = Query(default=None), limit: int = Query(default=200,ge=1,le=500)) -> dict[str, object]:
    try:
        return store.economic_history(economic_entity_id=economic_entity_id,mission_id=mission_id,valid_at=valid_at,known_at=known_at,limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.get("/v1/operational-memory/spec")
def get_operational_memory_spec() -> dict[str, object]:
    return operational_memory_spec()


@app.post("/v1/operations/competencies", status_code=201)
def create_operational_competency(payload: OperationalCompetencyRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    try:
        return CanonicalMutationService(store,actor_id=principal.client_id).run_sanitized(
            "operational.competency",store.create_operational_competency,actor_id=principal.client_id,
            competency_key=payload.competency_key,title=payload.title,description=payload.description,domain=payload.domain,
            created_by=principal.client_id,occurred_at=payload.occurred_at,observed_at=payload.observed_at,valid_from=payload.valid_from,valid_to=payload.valid_to)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.post("/v1/operations/skills", status_code=201)
def create_operational_skill(payload: OperationalSkillRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    try:
        return CanonicalMutationService(store,actor_id=principal.client_id).run_sanitized(
            "operational.skill",store.create_operational_skill,actor_id=principal.client_id,
            competency_id=payload.competency_id,skill_key=payload.skill_key,title=payload.title,description=payload.description,
            created_by=principal.client_id,occurred_at=payload.occurred_at,observed_at=payload.observed_at,valid_from=payload.valid_from,valid_to=payload.valid_to)
    except KeyError as exc: raise HTTPException(status_code=404,detail=f"operational competency not found: {exc.args[0]}") from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.post("/v1/operations/skill-versions", status_code=201)
def create_operational_skill_version(payload: OperationalSkillVersionRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    try:
        return CanonicalMutationService(store,actor_id=principal.client_id).run_sanitized(
            "operational.skill_version",store.create_operational_skill_version,actor_id=principal.client_id,
            skill_id=payload.skill_id,version_label=payload.version_label,implementation_version=payload.implementation_version,
            implementation_sha256=payload.implementation_sha256.lower(),contract=payload.contract,supersedes_skill_version_id=payload.supersedes_skill_version_id,
            created_by=principal.client_id,occurred_at=payload.occurred_at,observed_at=payload.observed_at,valid_from=payload.valid_from,valid_to=payload.valid_to)
    except KeyError as exc: raise HTTPException(status_code=404,detail=f"operational skill or version not found: {exc.args[0]}") from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.post("/v1/operations/skill-versions/{skill_version_id}/capabilities", status_code=201)
def add_operational_capability(skill_version_id: str, payload: OperationalCapabilityRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    try:
        return CanonicalMutationService(store,actor_id=principal.client_id).run_sanitized(
            "operational.capability",store.add_operational_capability,actor_id=principal.client_id,
            skill_version_id=skill_version_id,capability_key=payload.capability_key,contract=payload.contract,created_by=principal.client_id,
            occurred_at=payload.occurred_at,observed_at=payload.observed_at,valid_from=payload.valid_from,valid_to=payload.valid_to)
    except KeyError as exc: raise HTTPException(status_code=404,detail=f"operational skill version not found: {skill_version_id}") from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.post("/v1/operations/skill-versions/{skill_version_id}/proofs", status_code=201)
def record_operational_proof(skill_version_id: str, payload: OperationalProofRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    try:
        return CanonicalMutationService(store,actor_id=principal.client_id).run_sanitized(
            "operational.proof",store.record_operational_proof,actor_id=principal.client_id,
            skill_version_id=skill_version_id,proof_type=payload.proof_type.value,result=payload.result.value,
            artifact_ref=payload.artifact_ref,artifact_sha256=payload.artifact_sha256.lower(),evidence=payload.evidence,created_by=principal.client_id,
            executed_at=payload.executed_at,occurred_at=payload.occurred_at,observed_at=payload.observed_at,valid_from=payload.valid_from,valid_to=payload.valid_to)
    except KeyError as exc: raise HTTPException(status_code=404,detail=f"operational skill version not found: {skill_version_id}") from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
    except Exception as exc:
        state=getattr(exc,"sqlstate",None)
        if state in {"23514","55000"}: raise HTTPException(status_code=422,detail=str(exc).splitlines()[0]) from exc
        if state=="42501": raise HTTPException(status_code=403,detail=str(exc).splitlines()[0]) from exc
        raise


@app.post("/v1/operations/skill-versions/{skill_version_id}/status", status_code=201)
def set_operational_status(skill_version_id: str, payload: OperationalStatusRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal=principal_from_request(request)
    try:
        return CanonicalMutationService(store,actor_id=principal.client_id).run_sanitized(
            "operational.status",store.set_operational_status,actor_id=principal.client_id,
            skill_version_id=skill_version_id,status=payload.status.value,reason=payload.reason,evidence=payload.evidence,
            created_by=principal.client_id,occurred_at=payload.occurred_at)
    except KeyError as exc: raise HTTPException(status_code=404,detail=f"operational skill version not found: {skill_version_id}") from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc
    except Exception as exc:
        if getattr(exc,'sqlstate',None) in {'23514','55000'}: raise HTTPException(status_code=422,detail=str(exc).splitlines()[0]) from exc
        raise


@app.get("/v1/operations/skill-versions/{skill_version_id}")
def get_operational_skill_version(skill_version_id: str, store: StoreDep) -> dict[str, object]:
    try: return store.get_operational_skill_version(skill_version_id)
    except KeyError as exc: raise HTTPException(status_code=404,detail=f"operational skill version not found: {skill_version_id}") from exc


@app.get("/v1/operations/catalog")
def get_operational_catalog(store: StoreDep, status: str | None = Query(default=None,max_length=40),
    competency_key: str | None = Query(default=None,max_length=160), capability_key: str | None = Query(default=None,max_length=160),
    limit: int = Query(default=200,ge=1,le=500)) -> dict[str, object]:
    try: return {'items':store.operational_catalog(status=status,competency_key=competency_key,capability_key=capability_key,limit=limit)}
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc


@app.get("/v1/experience/spec")
def get_experience_graph_spec() -> dict[str, object]:
    return experience_graph_spec()


@app.post("/v1/experience/missions/{mission_id}/nodes", status_code=201)
def create_experience_graph_node(mission_id: str, payload: ExperienceGraphNodeRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal = principal_from_request(request)
    mutations = CanonicalMutationService(store, actor_id=principal.client_id)
    try:
        return mutations.run_sanitized(
            "experience.graph.node", store.create_experience_graph_node, actor_id=principal.client_id,
            mission_id=mission_id, node_type=payload.node_type.value, entity_ref=payload.entity_ref,
            payload=payload.payload, provenance=payload.provenance, memory_item_id=payload.memory_item_id,
            memory_version_id=payload.memory_version_id, occurred_at=payload.occurred_at, created_by=principal.client_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"memory not found: {exc.args[0]}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="experience graph entity already exists") from exc
        raise


@app.post("/v1/experience/missions/{mission_id}/edges", status_code=201)
def create_experience_graph_edge(mission_id: str, payload: ExperienceGraphEdgeRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal = principal_from_request(request)
    mutations = CanonicalMutationService(store, actor_id=principal.client_id)
    try:
        return mutations.run_sanitized(
            "experience.graph.edge", store.create_experience_graph_edge, actor_id=principal.client_id,
            mission_id=mission_id, from_node_id=payload.from_node_id, relation_type=payload.relation_type.value,
            to_node_id=payload.to_node_id, evidence=payload.evidence, occurred_at=payload.occurred_at, created_by=principal.client_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"experience node not found: {exc.args[0]}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="experience graph edge already exists") from exc
        raise


@app.get("/v1/experience/missions/{mission_id}/graph")
def get_mission_experience_graph(mission_id: str, store: StoreDep) -> dict[str, object]:
    try:
        return store.mission_experience_graph(mission_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/experience/applications", status_code=201)
def record_memory_application(payload: ApplicationRequest, request: Request, store: StoreDep, item_id: str = Query(...)) -> dict[str, object]:
    principal = principal_from_request(request)
    mutations = CanonicalMutationService(store, actor_id=principal.client_id)
    try:
        return mutations.record_application(
            item_id, actor_id=principal.client_id, action_ref=payload.action_ref, applied_by_client_id=principal.client_id,
            mission_id=payload.mission_id, decision_id=payload.decision_id, context=payload.context, occurred_at=payload.occurred_at,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"memory not found: {item_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/experience/applications/{application_id}/outcome", status_code=201)
def record_memory_outcome(application_id: str, payload: OutcomeRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal = principal_from_request(request)
    mutations = CanonicalMutationService(store, actor_id=principal.client_id)
    try:
        return mutations.record_outcome(
            application_id, principal=principal, success=payload.success, outcome_type=payload.outcome_type,
            expected=payload.expected, actual=payload.actual, confidence_delta=payload.confidence_delta,
            evidence=payload.evidence, occurred_at=payload.occurred_at,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"application not found: {application_id}") from exc
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(status_code=409, detail="outcome already recorded for application") from exc
        raise


@app.get("/v1/experience/graph")
def experience_graph(store: StoreDep, node_type: str = Query(..., max_length=80), node_id: str = Query(..., max_length=300), limit: int = Query(100, ge=1, le=500)) -> dict[str, object]:
    return {"edges": store.experience_graph(node_type=node_type.strip().upper(), node_id=node_id, limit=limit)}


@app.get("/v1/memories/{item_id}/learning")
def memory_version_learning(item_id: str, store: StoreDep) -> dict[str, object]:
    return {"item_id": item_id, "versions": store.version_learning(item_id)}


@app.post("/v1/leases/{lease_key}/acquire")
def acquire_lease(lease_key: str, payload: LeaseAcquireRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal = principal_from_request(request)
    try:
        return CanonicalMutationService(store, actor_id=principal.client_id).acquire_lease(lease_key, ttl_seconds=payload.ttl_seconds)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/leases/{lease_key}/release")
def release_lease(lease_key: str, payload: LeaseReleaseRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal = principal_from_request(request)
    try:
        return CanonicalMutationService(store, actor_id=principal.client_id).release_lease(lease_key, fencing_token=payload.fencing_token)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="lease not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConcurrencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/context/retrieve")
def retrieve_context(payload: ContextRequest, gateway: GatewayDep) -> dict[str, object]:
    result = gateway.retrieve_context(
        payload.query,
        namespaces=tuple(ns.strip().upper() for ns in payload.namespaces),
        limit=payload.limit,
        mission_id=payload.mission_id,
        session_id=payload.session_id,
        valid_at=payload.valid_at,
        known_at=payload.known_at,
    )
    return {
        "query": result.query,
        "selected": list(result.selected),
        "conflicts": list(result.conflicts),
        "state": result.state,
        "retrieval_modes": list(result.retrieval_modes),
        "trace_id": result.trace_id,
    }


@app.post("/v1/context/retrieve/explain")
def retrieve_context_explain(payload: ContextRequest, gateway: GatewayDep) -> dict[str, object]:
    result = gateway.retrieve_context(
        payload.query,
        namespaces=tuple(ns.strip().upper() for ns in payload.namespaces),
        limit=payload.limit,
        mission_id=payload.mission_id,
        session_id=payload.session_id,
        valid_at=payload.valid_at,
        known_at=payload.known_at,
    )
    selected = list(result.selected)
    conflicts = list(result.conflicts)
    retrieval_modes = list(result.retrieval_modes)
    return {
        "query": result.query,
        "selected": selected,
        "conflicts": conflicts,
        "state": result.state,
        "retrieval_modes": retrieval_modes,
        "trace_id": result.trace_id,
        "explanation": build_retrieval_explanation(
            query=result.query,
            selected=selected,
            conflicts=conflicts,
            retrieval_modes=retrieval_modes,
            trace_id=result.trace_id,
        ),
    }


@app.post("/v1/checkpoints", status_code=201)
def save_checkpoint(payload: CheckpointRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal = principal_from_request(request)
    return CanonicalMutationService(store, actor_id=principal.client_id).save_checkpoint(
        actor_id=principal.client_id, namespace=payload.namespace.strip().upper(), mission_id=payload.mission_id,
        step_index=payload.step_index, state=payload.state, checkpoint_id=payload.checkpoint_id, project_id=payload.project_id,
        occurred_at=payload.occurred_at, observed_at=payload.observed_at,
        valid_from=payload.valid_from, valid_to=payload.valid_to,
    )


@app.get("/v1/checkpoints/{mission_id}/latest")
def latest_checkpoint(
    mission_id: str,
    store: StoreDep,
    namespace: str | None = Query(default=None, max_length=120),
    valid_at: datetime | None = Query(default=None),
    known_at: datetime | None = Query(default=None),
) -> dict[str, object]:
    value = store.latest_checkpoint(mission_id, [namespace.strip().upper()] if namespace else None, valid_at=valid_at, known_at=known_at)
    if value is None:
        raise HTTPException(status_code=404, detail="checkpoint not found")
    return value


@app.post("/v1/memories/classify")
def classify_memories(payload: ClassificationRequest, request: Request, store: StoreDep) -> dict[str, object]:
    principal = principal_from_request(request)
    result = CanonicalMutationService(store, actor_id=principal.client_id).classify(
        payload.item_ids, payload.operator_class.value, actor_id=principal.client_id
    )
    return {**result, "direct_delete": False}


@app.get("/v1/reports/operational.md", response_class=PlainTextResponse)
def operational_report(store: StoreDep) -> PlainTextResponse:
    body = render_operational_report(store.summary())
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=MEMORY_OPERATIONAL_REPORT.md"},
    )


@app.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics(store: StoreDep) -> PlainTextResponse:
    summary = store.summary()

    def metric(name: str, value: object) -> str:
        try:
            numeric = value if isinstance(value, (str, int, float)) else 0
            return f"{name} {float(numeric):.6f}"
        except (TypeError, ValueError):
            return f"{name} 0"

    lines = [
        "# HELP memory_service_up Memory API health indicator.",
        "# TYPE memory_service_up gauge",
        "memory_service_up 1",
        "# TYPE memory_memories_total gauge",
        metric("memory_memories_total", summary.get("memories_total")),
        "# TYPE memory_retrievals_total counter",
        metric("memory_retrievals_total", summary.get("retrievals")),
        "# TYPE memory_applications_total counter",
        metric("memory_applications_total", summary.get("applications")),
        "# TYPE memory_successes_total counter",
        metric("memory_successes_total", summary.get("successes")),
        "# TYPE memory_failures_total counter",
        metric("memory_failures_total", summary.get("failures")),
        "# TYPE memory_conflicts_total counter",
        metric("memory_conflicts_total", summary.get("conflicts")),
        "# TYPE memory_audit_events_total counter",
        metric("memory_audit_events_total", summary.get("audit_events")),
        "# TYPE memory_purge_direct_enabled gauge",
        "memory_purge_direct_enabled 0",
    ]
    return PlainTextResponse(
        "\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/v1/derived-artifacts")
def derived_artifacts(
    store: StoreDep, item_id: str | None = Query(default=None,max_length=240),
    artifact_type: str | None = Query(default=None,max_length=80),
    status: str | None = Query(default=None,max_length=20), limit: int = Query(100,ge=1,le=500),
) -> dict[str, object]:
    return {"items":store.list_derived_artifacts(item_id=item_id,artifact_type=artifact_type,status=status,limit=limit)}


@app.get("/v1/derived-artifacts/{artifact_id}/dependencies")
def derived_artifact_dependencies(artifact_id: str, store: StoreDep) -> dict[str, object]:
    return {"artifact_id":artifact_id,"dependencies":store.artifact_dependencies(artifact_id)}


@app.post("/v1/purge")
def purge_disabled() -> None:
    raise HTTPException(status_code=405, detail="Purge direto proibido. M12 governa P0-UI-B; use lifecycle DELETE_ELIGIBLE -> QUARANTINED -> PURGED.")


class LifecycleHoldRequest(BaseModel):
    item_id: str = Field(min_length=1, max_length=120)
    hold_type: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=4000)


class LifecycleRequestPayload(BaseModel):
    item_id: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=4000)
    recovery_window_seconds: int = Field(ge=0, le=604800)
    evidence: dict[str, Any] = Field(default_factory=dict)


class LifecycleEvidencePayload(BaseModel):
    evidence: dict[str, Any] = Field(default_factory=dict)


class ErasureCreatePayload(BaseModel):
    lifecycle_request_id: str = Field(min_length=1, max_length=160)
    reason_code: str = Field(min_length=1, max_length=64)
    backup_cutoff_at: datetime | None = None


class ErasureReplayPayload(BaseModel):
    source_ref: str = Field(min_length=1, max_length=500)


@app.get("/v1/ui-governance/spec")
def get_ui_governance_spec(store: StoreDep) -> dict[str, object]:
    try:
        status = LifecycleManager(store).gate_status().get("status", "PENDING")
    except Exception:
        logger.exception("ui governance gate status lookup failed; returning PENDING")
        status = "PENDING"
    return ui_governance_spec(gate_status=str(status))


@app.get("/v1/lifecycle/spec")
def get_lifecycle_spec(store: StoreDep) -> dict[str, Any]:
    manager = LifecycleManager(store)
    try:
        status = manager.gate_status().get("status", "PENDING")
    except Exception:
        logger.exception("lifecycle gate status lookup failed; returning PENDING")
        status = "PENDING"
    return lifecycle_spec(gate_status=str(status))


@app.get("/v1/lifecycle/m12")
def get_lifecycle_m12(store: StoreDep) -> dict[str, Any]:
    return LifecycleManager(store).gate_status()


@app.post("/v1/lifecycle/holds", status_code=201)
def create_lifecycle_hold(payload: LifecycleHoldRequest, request: Request, store: StoreDep) -> dict[str, Any]:
    actor = principal_from_request(request).client_id
    manager = LifecycleManager(store)
    return CanonicalMutationService(store, actor_id=actor).run_sanitized(
        "lifecycle.create_hold", manager.create_hold, item_id=payload.item_id,
        hold_type=payload.hold_type, reason=payload.reason, actor=actor, actor_id=actor,
    )


@app.post("/v1/lifecycle/holds/{hold_id}/release")
def release_lifecycle_hold(hold_id: str, request: Request, store: StoreDep) -> dict[str, Any]:
    actor = principal_from_request(request).client_id
    manager = LifecycleManager(store)
    return CanonicalMutationService(store, actor_id=actor).run_sanitized(
        "lifecycle.release_hold", manager.release_hold, hold_id=hold_id, actor=actor, actor_id=actor,
    )


@app.post("/v1/lifecycle/requests", status_code=201)
def create_lifecycle_request(payload: LifecycleRequestPayload, request: Request, store: StoreDep) -> dict[str, Any]:
    actor = principal_from_request(request).client_id
    manager = LifecycleManager(store)
    return CanonicalMutationService(store, actor_id=actor).run_sanitized(
        "lifecycle.request_purge", manager.request_purge, item_id=payload.item_id, reason=payload.reason,
        recovery_window_seconds=payload.recovery_window_seconds, evidence=payload.evidence, actor=actor, actor_id=actor,
    )


@app.get("/v1/lifecycle/requests/{request_id}")
def get_lifecycle_request(request_id: str, store: StoreDep) -> dict[str, Any]:
    return LifecycleManager(store).get_request(request_id)


def _run_lifecycle_action(action: str, request_id: str, payload: LifecycleEvidencePayload,
                          request: Request, store: PostgresMemoryStore) -> dict[str, Any]:
    actor = principal_from_request(request).client_id
    manager = LifecycleManager(store)
    fn = getattr(manager, action)
    return CanonicalMutationService(store, actor_id=actor).run_sanitized(
        f"lifecycle.{action}", fn, request_id=request_id, evidence=payload.evidence, actor=actor, actor_id=actor,
    )


@app.post("/v1/lifecycle/requests/{request_id}/quarantine")
def lifecycle_quarantine(request_id: str, payload: LifecycleEvidencePayload, request: Request, store: StoreDep) -> dict[str, Any]:
    return _run_lifecycle_action("quarantine", request_id, payload, request, store)


@app.post("/v1/lifecycle/requests/{request_id}/approve")
def lifecycle_approve(request_id: str, payload: LifecycleEvidencePayload, request: Request, store: StoreDep) -> dict[str, Any]:
    return _run_lifecycle_action("approve", request_id, payload, request, store)


@app.post("/v1/lifecycle/requests/{request_id}/purge")
def lifecycle_purge(request_id: str, payload: LifecycleEvidencePayload, request: Request, store: StoreDep) -> dict[str, Any]:
    return _run_lifecycle_action("purge", request_id, payload, request, store)


@app.post("/v1/lifecycle/requests/{request_id}/recover")
def lifecycle_recover(request_id: str, payload: LifecycleEvidencePayload, request: Request, store: StoreDep) -> dict[str, Any]:
    return _run_lifecycle_action("recover", request_id, payload, request, store)


@app.post("/v1/lifecycle/requests/{request_id}/finalize")
def lifecycle_finalize(request_id: str, payload: LifecycleEvidencePayload, request: Request, store: StoreDep) -> dict[str, Any]:
    return _run_lifecycle_action("finalize", request_id, payload, request, store)


@app.post("/v1/lifecycle/m12/close")
def close_lifecycle_m12(payload: LifecycleEvidencePayload, request: Request, store: StoreDep) -> dict[str, Any]:
    actor = principal_from_request(request).client_id
    manager = LifecycleManager(store)
    return CanonicalMutationService(store, actor_id=actor).run_sanitized(
        "lifecycle.close_m12", manager.close_m12, evidence=payload.evidence, actor=actor, actor_id=actor,
    )


@app.get("/v1/erasure/spec")
def get_erasure_spec() -> dict[str, Any]:
    return erasure_spec()


@app.get("/v1/erasure/p18")
def get_erasure_p18(store: StoreDep) -> dict[str, Any]:
    return ErasureManager(store).gate_status()


@app.post("/v1/erasure/requests", status_code=201)
def create_erasure_request(payload: ErasureCreatePayload, request: Request, store: StoreDep) -> dict[str, Any]:
    actor = principal_from_request(request).client_id
    manager = ErasureManager(store)
    return CanonicalMutationService(store, actor_id=actor).run_sanitized(
        "legal_erasure.record", manager.record_erasure, lifecycle_request_id=payload.lifecycle_request_id,
        reason_code=payload.reason_code, backup_cutoff_at=payload.backup_cutoff_at, actor=actor, actor_id=actor,
    )


@app.get("/v1/erasure/requests/{erasure_id}")
def get_erasure_request(erasure_id: str, store: StoreDep) -> dict[str, Any]:
    return ErasureManager(store).get_erasure(erasure_id)


@app.post("/v1/erasure/replay")
def replay_erasure(payload: ErasureReplayPayload, request: Request, store: StoreDep) -> dict[str, Any]:
    actor = principal_from_request(request).client_id
    manager = ErasureManager(store)
    return CanonicalMutationService(store, actor_id=actor).run_sanitized(
        "legal_erasure.replay", manager.replay, source_ref=payload.source_ref, actor=actor, actor_id=actor,
    )


@app.post("/v1/erasure/p18/close")
def close_erasure_p18(payload: LifecycleEvidencePayload, request: Request, store: StoreDep) -> dict[str, Any]:
    actor = principal_from_request(request).client_id
    manager = ErasureManager(store)
    return CanonicalMutationService(store, actor_id=actor).run_sanitized(
        "legal_erasure.close_p18", manager.close_p18, evidence=payload.evidence, actor=actor, actor_id=actor,
    )


# V5.1 / M17 human operational governance API.

class HumanDisplayMetadataPatch(BaseModel):
    human_title: str | None = Field(default=None, min_length=1, max_length=300)
    human_summary: str | None = Field(default=None, min_length=1, max_length=1200)
    source_context_summary: str | None = Field(default=None, max_length=1200)
    topic_tags: list[str] | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=500)


class HumanActionRequest(BaseModel):
    reason: str = Field(default="AÃƒÂ§ÃƒÂ£o administrativa pelo painel", min_length=1, max_length=500)


class HumanDeleteRequest(BaseModel):
    reason: str = Field(default="ExclusÃƒÂ£o solicitada pelo operador", min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=240)
    quarantine_seconds: int = Field(default=86400, ge=60, le=604800)


class HumanDeleteBatchRequest(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=500)
    reason: str = Field(default="ExclusÃƒÂ£o em lote solicitada pelo operador", min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=240)
    quarantine_seconds: int = Field(default=86400, ge=60, le=604800)


class HumanPromotionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    evidence: dict[str, Any] = Field(default_factory=dict)


def _human_manager(store: PostgresMemoryStore) -> HumanGovernanceManager:
    return HumanGovernanceManager(store)


@app.get("/v1/admin/panel/overview")
def human_panel_overview(store: StoreDep) -> dict[str, Any]:
    return _human_manager(store).overview()


@app.get("/v1/admin/panel/scopes")
def human_panel_scopes(store: StoreDep) -> dict[str, Any]:
    return _human_manager(store).scopes()


@app.get("/v1/admin/panel/global-memories")
def human_panel_global_memories(
    store: StoreDep,
    q: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    return {"contract": HUMAN_GOVERNANCE_CONTRACT, "items": _human_manager(store).global_memories(query=q, limit=limit)}


@app.get("/v1/admin/panel/projects")
def human_panel_projects(store: StoreDep) -> dict[str, Any]:
    return {"contract": HUMAN_GOVERNANCE_CONTRACT, "items": _human_manager(store).projects()}


@app.get("/v1/admin/panel/projects/{project_id}/memories")
def human_panel_project_memories(
    project_id: str,
    store: StoreDep,
    q: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    return {"contract": HUMAN_GOVERNANCE_CONTRACT, "project_id": project_id, "items": _human_manager(store).project_memories(project_id, query=q, limit=limit)}


@app.get("/v1/admin/memories/{item_id}/operator-view")
def human_operator_view(item_id: str, store: StoreDep) -> dict[str, Any]:
    try:
        return _human_manager(store).operator_view(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"memory not found: {item_id}") from exc


@app.patch("/v1/admin/memories/{item_id}/display-metadata")
def human_update_display_metadata(item_id: str, payload: HumanDisplayMetadataPatch, request: Request, store: StoreDep) -> dict[str, Any]:
    principal = principal_from_request(request)
    try:
        return CanonicalMutationService(store, actor_id=principal.client_id).run_sanitized(
            "human.display_metadata",
            _human_manager(store).update_display_metadata,
            actor_id=principal.client_id,
            item_id=item_id,
            actor=principal.client_id,
            human_title=payload.human_title,
            human_summary=payload.human_summary,
            source_context_summary=payload.source_context_summary,
            topic_tags=payload.topic_tags,
            reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"memory not found: {item_id}") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _human_class_action(item_id: str, payload: HumanActionRequest, request: Request, store: PostgresMemoryStore, action: str) -> dict[str, Any]:
    principal = principal_from_request(request)
    manager = _human_manager(store)
    fn = manager.protect if action == "protect" else manager.archive
    try:
        return CanonicalMutationService(store, actor_id=principal.client_id).run_sanitized(
            f"human.{action}", fn, actor_id=principal.client_id,
            item_id=item_id, actor=principal.client_id, reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"memory not found: {item_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/admin/memories/{item_id}/protect")
def human_protect(item_id: str, payload: HumanActionRequest, request: Request, store: StoreDep) -> dict[str, Any]:
    return _human_class_action(item_id, payload, request, store, "protect")


@app.post("/v1/admin/memories/{item_id}/archive")
def human_archive(item_id: str, payload: HumanActionRequest, request: Request, store: StoreDep) -> dict[str, Any]:
    return _human_class_action(item_id, payload, request, store, "archive")


@app.post("/v1/admin/memories/{item_id}/delete")
def human_delete(item_id: str, payload: HumanDeleteRequest, request: Request, store: StoreDep) -> dict[str, Any]:
    principal = principal_from_request(request)
    try:
        return CanonicalMutationService(store, actor_id=principal.client_id).run_sanitized(
            "human.delete",
            _human_manager(store).delete_memory,
            actor_id=principal.client_id,
            item_id=item_id,
            actor=principal.client_id,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
            quarantine_seconds=payload.quarantine_seconds,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"memory not found: {item_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/admin/memories/delete-batch")
def human_delete_batch(payload: HumanDeleteBatchRequest, request: Request, store: StoreDep) -> dict[str, Any]:
    principal = principal_from_request(request)
    return CanonicalMutationService(store, actor_id=principal.client_id).run_sanitized(
        "human.delete_batch",
        _human_manager(store).delete_batch,
        actor_id=principal.client_id,
        item_ids=payload.item_ids,
        actor=principal.client_id,
        reason=payload.reason,
        idempotency_key=payload.idempotency_key,
        quarantine_seconds=payload.quarantine_seconds,
    )


@app.post("/v1/admin/memories/{item_id}/undo-delete")
def human_undo_delete(item_id: str, payload: HumanActionRequest, request: Request, store: StoreDep) -> dict[str, Any]:
    principal = principal_from_request(request)
    try:
        return CanonicalMutationService(store, actor_id=principal.client_id).run_sanitized(
            "human.undo_delete",
            _human_manager(store).undo_delete,
            actor_id=principal.client_id,
            item_id=item_id,
            actor=principal.client_id,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/admin/memories/{item_id}/promote-scope")
def human_promote_scope(item_id: str, payload: HumanPromotionRequest, request: Request, store: StoreDep) -> dict[str, Any]:
    principal = principal_from_request(request)
    try:
        return CanonicalMutationService(store, actor_id=principal.client_id).run_sanitized(
            "human.promote_scope",
            _human_manager(store).promote_project_to_global,
            actor_id=principal.client_id,
            item_id=item_id,
            actor=principal.client_id,
            reason=payload.reason,
            evidence=payload.evidence,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"memory not found: {item_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/admin/panel/report.md", response_class=PlainTextResponse)
def human_panel_report(store: StoreDep) -> PlainTextResponse:
    return PlainTextResponse(
        _human_manager(store).report_markdown(),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=MEMORIA_PERMANENTE_HUMAN_GOVERNANCE_REPORT.md"},
    )


# V5.1 / M16 integrity governance API. Browser sessions are intentionally not
# permitted to mutate this namespace; these routes require signed HMAC admin.

class IntegrityManifestRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


class IntegrityAnchorRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.get("/v1/admin/integrity/status")
def integrity_status(store: StoreDep) -> dict[str, Any]:
    return IntegrityGovernance(store).status()


@app.post("/v1/admin/integrity/manifests", status_code=201)
def integrity_create_manifest(payload: IntegrityManifestRequest, request: Request, store: StoreDep) -> dict[str, Any]:
    principal = principal_from_request(request)
    try:
        return CanonicalMutationService(store, actor_id=principal.client_id).run_sanitized(
            "integrity.create",
            IntegrityGovernance(store).create_audit_manifest,
            actor_id=principal.client_id,
            actor=principal.client_id,
            metadata=payload.metadata,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/admin/integrity/manifests/{manifest_id}/verify")
def integrity_verify_manifest(manifest_id: str, request: Request, store: StoreDep) -> dict[str, Any]:
    principal = principal_from_request(request)
    try:
        return CanonicalMutationService(store, actor_id=principal.client_id).run_sanitized(
            "integrity.verify",
            IntegrityGovernance(store).verify,
            actor_id=principal.client_id,
            manifest_id=manifest_id,
            actor=principal.client_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"integrity manifest not found: {manifest_id}") from exc


@app.post("/v1/admin/integrity/manifests/{manifest_id}/anchor", status_code=201)
def integrity_anchor_manifest(manifest_id: str, payload: IntegrityAnchorRequest, request: Request, store: StoreDep) -> dict[str, Any]:
    principal = principal_from_request(request)
    try:
        return CanonicalMutationService(store, actor_id=principal.client_id).run_sanitized(
            "integrity.reanchor",
            IntegrityGovernance(store).anchor_existing,
            actor_id=principal.client_id,
            manifest_id=manifest_id,
            actor=principal.client_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"integrity manifest not found: {manifest_id}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/admin/integrity/keys/rotate")
def integrity_rotate_key(request: Request, store: StoreDep) -> dict[str, Any]:
    principal = principal_from_request(request)
    return CanonicalMutationService(store, actor_id=principal.client_id).run_sanitized(
        "integrity.rotate_key",
        IntegrityGovernance(store).rotate_key,
        actor_id=principal.client_id,
        actor=principal.client_id,
    )






