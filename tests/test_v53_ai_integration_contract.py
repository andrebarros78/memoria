from pathlib import Path

from memory_permanent.ai_integration_adapter import AI_INTEGRATION_CONTRACT
from memory_permanent.api import app, health
from memory_permanent.client_auth import required_permission_for_path

ROOT = Path(__file__).resolve().parents[1]


def test_v53_routes_are_inside_existing_memory_api():
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/v1/ai-integration/spec" in paths
    assert "/v1/ai-integration/suggestions" in paths
    assert "/v1/ai-integration/suggestions/{suggestion_id}/decisions" in paths
    assert "/v1/ai-integration/suggestions/{suggestion_id}/promote" in paths
    assert app.title == "MEMORIA-PERMANENTE"


def test_v53_health_exposes_adapter_capability_without_changing_product_identity():
    body = health()
    assert body["ai_integration_adapter"] == AI_INTEGRATION_CONTRACT
    assert body["product_id"] == "memoria-permanente"


def test_v53_permissions_are_least_privilege():
    assert required_permission_for_path("/v1/ai-integration/spec", "GET") == "memory:read"
    assert required_permission_for_path("/v1/ai-integration/suggestions", "POST") == "memory:ai-suggest"
    assert required_permission_for_path("/v1/ai-integration/suggestions", "GET") == "memory:ai-review"
    assert required_permission_for_path("/v1/ai-integration/suggestions/ais-x/decisions", "POST") == "memory:ai-review"
    assert required_permission_for_path("/v1/ai-integration/suggestions/ais-x/promote", "POST") == "memory:ai-promote"


def test_v53_migration_is_rls_and_append_only():
    sql = (ROOT / "migrations" / "0045_ai_integration_adapter.sql").read_text(encoding="utf-8")
    assert "ai_integration_suggestions" in sql
    assert "ai_integration_decisions" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "schema_meta" in sql


def test_v53_store_methods_require_canonical_mutation():
    source = (ROOT / "src" / "memory_permanent" / "store.py").read_text(encoding="utf-8")
    assert "def record_ai_integration_suggestion" in source
    assert "require_canonical_mutation('ai.integration.suggestion.record')" in source
    assert "def record_ai_integration_decision" in source
    assert "require_canonical_mutation('ai.integration.decision.record')" in source


def test_v53_mcp_stays_api_bound_no_database_access():
    source = (ROOT / "src" / "memory_permanent" / "mcp_server.py").read_text(encoding="utf-8")
    assert "memory_ai_integration_spec" in source
    assert '"/v1/ai-integration/spec"' in source
    assert "PostgresMemoryStore" not in source


def test_v53_panel_surfaces_ai_integration_contract():
    index = (ROOT / "src" / "memory_permanent" / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "src" / "memory_permanent" / "static" / "app.js").read_text(encoding="utf-8")
    assert "AI Integration Adapter" in index
    assert "V5.3" in index
    assert "/v1/ai-integration/spec" in app_js
    assert "loadV53AIIntegration" in app_js
