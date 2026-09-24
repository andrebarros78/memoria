from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient

from memory_permanent.api import app
from memory_permanent.secret_sanitizer import SecretSanitizer

ROOT = Path(__file__).resolve().parents[1]


def _vault() -> Mock:
    vault = Mock()
    vault.put.side_effect = lambda **kwargs: "vault://memory/tenant_a/" + ("a" * 24)
    return vault


def test_secret_sanitizer_blocks_common_vendor_and_header_secret_keys() -> None:
    vault = _vault()
    sanitizer = SecretSanitizer(vault, "TENANT_A")
    source = {
        "headers": {
            "X-API-Key": "opaque-api-secret",
            "X-Auth-Token": "opaque-auth-secret",
            "Authorization": "Bearer opaque-bearer-secret",
        },
        "aws_secret_access_key": "opaque-aws-secret",
        "webhook_secret": "opaque-webhook-secret",
        "memory_key": "ordinary-memory-key",
    }
    clean = sanitizer.sanitize(source)
    assert clean["headers"]["X-API-Key"].startswith("vault://memory/")
    assert clean["headers"]["X-Auth-Token"].startswith("vault://memory/")
    assert clean["headers"]["Authorization"].startswith("vault://memory/")
    assert clean["aws_secret_access_key"].startswith("vault://memory/")
    assert clean["webhook_secret"].startswith("vault://memory/")
    assert clean["memory_key"] == "ordinary-memory-key"
    assert vault.put.call_count == 5


def test_secret_sanitizer_blocks_secret_labels_and_private_key_variants_in_text() -> None:
    vault = _vault()
    sanitizer = SecretSanitizer(vault, "TENANT_A")
    text = (
        "X-API-Key: opaque-a; X-Auth-Token=opaque-b; "
        "aws-secret-access-key=opaque-c\n"
        "-----BEGIN RSA PRIVATE KEY-----\nopaque-private-material\n-----END RSA PRIVATE KEY-----"
    )
    clean = sanitizer.sanitize(text)
    assert "opaque-a" not in clean
    assert "opaque-b" not in clean
    assert "opaque-c" not in clean
    assert "opaque-private-material" not in clean
    assert clean.count("vault://memory/") >= 4


def test_public_health_is_minimal_and_internal_details_are_authenticated() -> None:
    with TestClient(app) as client:
        public = client.get("/health")
        details = client.get("/v1/health/details")
    assert public.status_code == 200
    assert set(public.json()) == {"status", "service", "runtime_profile", "release_channel"}
    assert "database" not in public.json()
    assert "agent_skill_plane" not in public.json()
    assert "dna_sha256" not in public.json()
    assert details.status_code == 401


def test_interactive_api_documentation_is_not_served() -> None:
    registered = {getattr(route, "path", None) for route in app.routes}
    assert "/openapi.json" not in registered
    assert "/docs" not in registered
    assert "/redoc" not in registered
    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code in {401, 404}
        assert client.get("/docs").status_code in {401, 404}
        assert client.get("/redoc").status_code in {401, 404}


def test_browser_ui_does_not_advertise_mutations_for_read_only_bearer() -> None:
    html = (ROOT / "src" / "memory_permanent" / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "src" / "memory_permanent" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'data-class=' not in html
    assert 'id="selectAll"' not in html
    assert "/v1/memories/classify" not in js
    assert "state.selected" not in js
    assert "row-check" not in js
    assert "Classificação: somente via cliente HMAC autenticado." in html


def test_migration_0050_guards_legacy_security_definers() -> None:
    sql = (ROOT / "migrations" / "0050_security_definer_tenant_boundary.sql").read_text(encoding="utf-8")
    assert "cross-tenant legal erasure is forbidden" in sql
    assert "cross-tenant ontology transition is forbidden" in sql
    assert "cross-tenant lifecycle finalization is forbidden" in sql
    assert "OWNER TO memory_admin" in sql
    assert "REVOKE EXECUTE ON FUNCTION public.memory_apply_legal_erasure(text,text,text,text) FROM memory_app" in sql
    assert sql.count("SET search_path = pg_catalog, public, pg_temp") >= 7
