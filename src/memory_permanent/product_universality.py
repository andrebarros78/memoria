"""Universal product contract for MEMORIA-PERMANENTE.

V5.5 freezes the product as universal context and memory infrastructure. It may
be deployed beside one consumer, on another host, on a dedicated server, or as
a shared service. AI is an optional consumer/capability, never a core runtime
dependency.
"""

from __future__ import annotations

from typing import Any

from .product_dna import public_identity

UNIVERSAL_PRODUCT_CONTRACT = "MEMORIA_PERMANENTE_UNIVERSAL_PRODUCT_V2"
ARCHITECTURE_GENERATION = "V5.5"
PRODUCT_CLASS = "UNIVERSAL_CONTEXT_MEMORY_INFRASTRUCTURE"
APPROVED_SERVICE_MODEL = (
    "A Memoria Permanente sempre atende um ou mais sistemas consumidores, mas permanece produto independente. "
    "Pode ser instalada junto do consumidor, em outra maquina, em servidor proprio ou como servico compartilhado."
)

V5_5_CLOSURE_POINTS = [
    "DNA_UNIVERSAL_DEFINITIVO",
    "CONTRATO_UNIVERSAL_DE_CONSUMIDOR",
    "PERFIS_DE_IMPLANTACAO",
    "PERFIS_DE_CAPACIDADE",
    "ADAPTERS_OFICIAIS",
    "ISOLAMENTO_UNIVERSAL",
    "KIT_DE_CONFORMIDADE",
    "PORTABILIDADE_COMPROVADA",
]


def product_universality_spec() -> dict[str, Any]:
    identity = public_identity()
    return {
        "contract": UNIVERSAL_PRODUCT_CONTRACT,
        "architecture_generation": ARCHITECTURE_GENERATION,
        "product_id": identity["product_id"],
        "product_name": identity.get("product_name"),
        "product_class": PRODUCT_CLASS,
        "product_scope": "UNIVERSAL_MEMORY_CONTEXT_STATE_CONTINUITY_AND_LEARNING_INFRASTRUCTURE",
        "approved_service_model": APPROVED_SERVICE_MODEL,
        "is_universal_product": True,
        "runtime_identity_binding": False,
        "consumer_identity_binding": False,
        "ai_engine_identity_binding": False,
        "ai_required_for_core": False,
        "current_proven_runtime": {
            "platform": "WINDOWS_JNS",
            "path": r"C:\New Projet\MEMORIA-PERMANENTE",
            "runtime_profile": "V5.3-PRIMARY",
            "release_channel": "v5.3-primary-promoted",
            "meaning": "operationally proven runtime target, not product identity",
        },
        "development_and_ci_role": {
            "platform": "LINUX",
            "meaning": "development, CI, build, comparison and synchronization target until production-runtime proof is completed",
        },
        "deployment_profiles": {
            "co_located": "memory service and consumer on the same host",
            "dedicated_host": "memory service on another controlled machine or server",
            "shared_service": "one governed memory service serving multiple isolated consumers",
            "distributed_ha": "future high-availability placement without changing the consumer contract",
        },
        "capability_profiles": {
            "CORE": ["persistence", "context", "state", "security"],
            "CONVERSATIONAL": ["conversation_context", "session_continuity", "customer_context"],
            "AI": ["external_ai_integration", "embeddings", "semantic_retrieval", "ai_suggestions"],
            "OPERATIONAL": ["checkpoint", "resume", "recovery", "operational_state"],
            "INTELLIGENCE": ["learning", "experience", "procedures", "knowledge"],
            "FULL": ["CORE", "CONVERSATIONAL", "AI", "OPERATIONAL", "INTELLIGENCE"],
        },
        "consumer_classes": {
            "ai_and_agents": "GPT, Claude, Gemini, local models and future AI systems through governed public integration",
            "conversational_systems": "WhatsApp API, chat, support, sales and CRM contexts",
            "intelligence_systems": "Market Intelligence, Marketing Intelligence and analytical products",
            "infrastructure_orchestrators": "LMCP, WMCP and other execution/orchestration systems",
            "traditional_applications": "ERP, CRM, marketplace, SaaS and non-AI applications",
            "future_consumers": "any consumer that satisfies the public contract and conformance gates",
        },
        "consumer_systems": {
            "market_intelligence_ai": "authorized external consumer through governed public integration",
            "whatsapp_api": "eligible conversational consumer through scoped context/memory contracts",
            "lmcp": "authorized orchestration/runtime consumer through signed API or MCP boundary",
            "wmcp": "authorized orchestration/runtime consumer through signed API or MCP boundary",
            "other_consumers": "allowed only through public contracts, scoped credentials and isolation policy",
        },
        "v5_5_closure_points": list(V5_5_CLOSURE_POINTS),
        "non_goals": [
            "not a Windows-only product",
            "not a Linux-only product",
            "not a Market Intelligence submodule",
            "not a WhatsApp submodule",
            "not a WMCP or LMCP internal database",
            "not an internal AI API",
            "not dependent on any AI provider to operate its core",
            "not a direct database extension for external agents",
        ],
        "guarantees": {
            "stable_identity": "product_id and DNA are independent from runtime branch names",
            "portable_contracts": ["REST", "OpenAPI", "MCP", "PostgreSQL schema migrations"],
            "governed_memory_core": True,
            "external_ai_suggests_only": True,
            "memory_governs_promotions": True,
            "direct_external_database_access": False,
            "consumer_decoupling": True,
            "co_located_or_remote_deployment": True,
            "shared_service_supported_by_contract": True,
            "ai_optional_and_replaceable": True,
            "llm_inference_owned_by_memory_core": False,
            "cross_project_memory_leakage_forbidden": True,
        },
    }
