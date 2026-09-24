from __future__ import annotations

import importlib.util
import os
import platform
from dataclasses import dataclass
from typing import Any

from .product_universality import (
    ARCHITECTURE_GENERATION,
    PRODUCT_CLASS,
    UNIVERSAL_PRODUCT_CONTRACT,
    V5_5_CLOSURE_POINTS,
)

V55_RUNTIME_CONTRACT = "MEMORIA_PERMANENTE_V5_5_RUNTIME_V1"
V55_CONSUMER_CONTRACT = "MEMORIA_PERMANENTE_CONSUMER_V1"
V55_CONFORMANCE_CONTRACT = "MEMORIA_PERMANENTE_CONFORMANCE_V1"
V55_RUNTIME_PROFILE = "V5.5-PRIMARY"
V55_RELEASE_CHANNEL = "MEMORIA_PERMANENTE_CANONICAL_1.0"
V55_CONSTRUCTION_RUNTIME_PROFILE = "V5.5-CONSTRUCTION"
V55_CONSTRUCTION_RELEASE_CHANNEL = "v5.5-construction"

UNIVERSAL_OPERATIONS: dict[str, dict[str, str]] = {
    "memory.capture": {"transport": "REST", "method": "POST", "path": "/v1/memories", "permission": "memory:write"},
    "memory.context": {"transport": "REST", "method": "POST", "path": "/v1/context/retrieve", "permission": "memory:context"},
    "memory.search": {"transport": "REST", "method": "POST", "path": "/v1/context/retrieve", "permission": "memory:context"},
    "memory.checkpoint": {"transport": "REST", "method": "POST", "path": "/v1/checkpoints", "permission": "memory:checkpoint"},
    "memory.resume": {"transport": "REST", "method": "GET+POST", "path": "/v1/checkpoints/{mission_id}/latest + /v1/context/retrieve", "permission": "memory:checkpoint+memory:context"},
    "memory.state": {"transport": "REST", "method": "GET", "path": "/v1/checkpoints/{mission_id}/latest", "permission": "memory:checkpoint"},
}

DEPLOYMENT_PROFILES: dict[str, dict[str, Any]] = {
    "CO_LOCATED": {
        "description": "Memory service and one or more consumers on the same host.",
        "network": "loopback preferred",
        "contract_changes_required": False,
    },
    "DEDICATED_HOST": {
        "description": "Memory service runs on another controlled host.",
        "network": "HTTPS required outside loopback",
        "contract_changes_required": False,
    },
    "SHARED_SERVICE": {
        "description": "One governed service serves multiple isolated consumers.",
        "network": "HTTPS required outside loopback",
        "contract_changes_required": False,
        "tenant_and_scope_isolation_required": True,
    },
    "DISTRIBUTED_HA": {
        "description": "High-availability/distributed placement without consumer-domain changes.",
        "network": "HTTPS and authenticated service boundary required",
        "contract_changes_required": False,
        "state_replication_proof_required": True,
    },
}

CAPABILITY_PROFILES: dict[str, tuple[str, ...]] = {
    "CORE": ("persistence", "context", "state", "security"),
    "CONVERSATIONAL": ("conversation_context", "session_continuity", "customer_context"),
    "AI": ("external_ai_integration", "embeddings", "semantic_retrieval", "ai_suggestions"),
    "OPERATIONAL": ("checkpoint", "resume", "recovery", "operational_state"),
    "INTELLIGENCE": ("learning", "experience", "procedures", "knowledge"),
}
CAPABILITY_PROFILES["FULL"] = tuple(
    sorted({cap for profile in CAPABILITY_PROFILES.values() for cap in profile})
)

OFFICIAL_ADAPTERS: dict[str, dict[str, Any]] = {
    "REST_OPENAPI": {"module": "memory_permanent.api", "role": "universal public HTTP contract", "core_dependency": True},
    "MCP": {"module": "memory_permanent.mcp_server", "role": "agent/AI protocol adapter over signed API", "core_dependency": False},
    "MEMORY_CLIENT": {"module": "memory_permanent.consumer_adapter", "role": "reusable consumer-side adapter", "core_dependency": False},
    "AI_INTEGRATION": {"module": "memory_permanent.ai_integration_adapter", "role": "governed AI suggestions", "core_dependency": False},
    "CONVERSATIONAL": {"module": "memory_permanent.conversational_adapter", "role": "provider-neutral chat/WhatsApp context normalization", "core_dependency": False},
}

SECURITY_LAYERS: tuple[str, ...] = (
    "HMAC_SCOPED_CLIENT_AUTH",
    "ANTI_REPLAY_NONCE_WINDOW",
    "CAPABILITY_PERMISSIONS",
    "ROW_LEVEL_SECURITY",
    "TENANT_PROJECT_SCOPE_ISOLATION",
    "NO_DIRECT_EXTERNAL_DATABASE_ACCESS",
    "TLS_REQUIRED_FOR_NON_LOOPBACK_CLIENTS",
    "SECRET_SANITIZATION_AND_EXTERNAL_SECRET_STORE",
    "CANONICAL_MUTATION_GATE",
    "APPEND_ONLY_VERSIONING_AND_PROVENANCE",
    "INPUT_GUARD_AND_SIZE_LIMITS",
    "NO_HTTP_REDIRECT_FOR_CREDENTIALED_REQUESTS",
    "LIFECYCLE_HOLD_QUARANTINE_PURGE_GOVERNANCE",
    "BACKUP_RESTORE_AND_INTEGRITY_PROOFS",
    "OBSERVABILITY_AUDIT_AND_RETRIEVAL_TRACE",
)

CONFORMANCE_CHECKS: tuple[str, ...] = (
    "CAPTURE",
    "CONTEXT_RECOVERY",
    "POSITIVE_SCOPE_ACCESS",
    "NEGATIVE_SCOPE_ISOLATION",
    "AUTHENTICATION_AUTHORIZATION",
    "IDEMPOTENCY",
    "CHECKPOINT_RESUME",
    "RESTART_RECOVERY",
    "NO_DIRECT_DATABASE_ACCESS",
    "SECURITY_REGRESSION",
    "INTEGRITY_AUDIT",
)


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def adapter_inventory() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, meta in OFFICIAL_ADAPTERS.items():
        row = dict(meta)
        row["available"] = _module_available(str(meta["module"]))
        out[name] = row
    return out


def runtime_portability_snapshot() -> dict[str, Any]:
    system = platform.system().upper() or "UNKNOWN"
    return {
        "current_platform": system,
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "windows_proof": os.getenv("MEMORY_V55_WINDOWS_PROVEN", "0") == "1",
        "linux_proof": os.getenv("MEMORY_V55_LINUX_PROVEN", "0") == "1",
        "portable_client_network_policy": "HTTP_LOOPBACK_OR_HTTPS_REMOTE",
    }


def v55_runtime_spec() -> dict[str, Any]:
    adapters = adapter_inventory()
    return {
        "contract": V55_RUNTIME_CONTRACT,
        "consumer_contract": V55_CONSUMER_CONTRACT,
        "product_contract": UNIVERSAL_PRODUCT_CONTRACT,
        "architecture_generation": ARCHITECTURE_GENERATION,
        "product_class": PRODUCT_CLASS,
        "runtime_profile": V55_RUNTIME_PROFILE,
        "release_channel": (os.getenv("MEMORY_RELEASE_CHANNEL", V55_RELEASE_CHANNEL).strip() or V55_RELEASE_CHANNEL),
        "closure_points": list(V5_5_CLOSURE_POINTS),
        "closure_points_count": len(V5_5_CLOSURE_POINTS),
        "universal_operations": dict(UNIVERSAL_OPERATIONS),
        "deployment_profiles": dict(DEPLOYMENT_PROFILES),
        "capability_profiles": {k: list(v) for k, v in CAPABILITY_PROFILES.items()},
        "official_adapters": adapters,
        "all_official_adapters_available": all(row["available"] for row in adapters.values()),
        "ai_required_for_core": False,
        "external_llm_inference_owned_by_core": False,
        "direct_external_database_access": False,
        "security_layers": list(SECURITY_LAYERS),
        "security_layer_count": len(SECURITY_LAYERS),
        "conformance_checks": list(CONFORMANCE_CHECKS),
        "portability": runtime_portability_snapshot(),
    }


@dataclass(frozen=True, slots=True)
class ConformanceResult:
    compatible: bool
    passed: tuple[str, ...]
    failed: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": V55_CONFORMANCE_CONTRACT,
            "compatible": self.compatible,
            "passed": list(self.passed),
            "failed": list(self.failed),
        }


def evaluate_conformance(evidence: dict[str, Any]) -> ConformanceResult:
    normalized = {str(k).strip().upper(): bool(v) for k, v in evidence.items()}
    passed = tuple(check for check in CONFORMANCE_CHECKS if normalized.get(check, False))
    failed = tuple(check for check in CONFORMANCE_CHECKS if not normalized.get(check, False))
    return ConformanceResult(compatible=not failed, passed=passed, failed=failed)


def validate_profile_selection(deployment_profile: str, capability_profiles: list[str]) -> dict[str, Any]:
    deployment = str(deployment_profile or "").strip().upper()
    if deployment not in DEPLOYMENT_PROFILES:
        raise ValueError("unsupported deployment profile")
    requested = [str(x).strip().upper() for x in capability_profiles]
    if not requested:
        requested = ["CORE"]
    unknown = sorted({x for x in requested if x not in CAPABILITY_PROFILES})
    if unknown:
        raise ValueError("unsupported capability profile(s): " + ",".join(unknown))
    expanded = sorted({cap for name in requested for cap in CAPABILITY_PROFILES[name]})
    return {
        "deployment_profile": deployment,
        "capability_profiles": requested,
        "expanded_capabilities": expanded,
        "ai_required": "AI" in requested or "FULL" in requested,
        "core_always_required": True,
        "contract_changes_required": False,
    }
