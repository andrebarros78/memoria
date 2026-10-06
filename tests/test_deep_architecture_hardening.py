from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v55_recovery_delegates_to_canonical_launcher() -> None:
    recovery = (ROOT / ".agents" / "recovery" / "start-api.ps1").read_text(encoding="utf-8-sig")
    postgres = (ROOT / ".agents" / "recovery" / "start-postgres.ps1").read_text(encoding="utf-8-sig")
    assert "deploy\\canonical\\start-canonical.ps1" in recovery
    assert "MEMORY_DATABASE_URL=" not in recovery
    assert "MEMORY_DSN=" not in recovery
    assert "V5.5-PRIMARY" in recovery
    assert "MEMORIA_PERMANENTE_PG" in postgres
    assert "Start-Service" in postgres


def test_embedded_bootstrap_operator_class_matches_domain() -> None:
    store = (ROOT / "src" / "memory_permanent" / "store.py").read_text(encoding="utf-8-sig")
    assert "DESCART\u00c1VEL" in store
    assert "DESCART\u00c3\u0081VEL" not in store


def test_security_response_headers_are_defense_in_depth() -> None:
    from memory_permanent.product_dna import response_headers
    headers = response_headers()
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["Cache-Control"] == "no-store"


def test_runtime_workers_pin_canonical_database_and_runtime() -> None:
    launcher = (ROOT / "scripts" / "start_runtime_worker.ps1").read_text(encoding="utf-8-sig")
    assert "runtime\\api-clean\\Scripts\\python.exe" in launcher
    assert "memoria_permanente_v52_primary" in launcher
    assert "MEMORY_DEFAULT_TENANT='LEGACY'" in launcher
    assert ".venv" not in launcher


def test_clean_database_bootstrap_keeps_runtime_role_non_owner() -> None:
    bootstrap = (ROOT / "scripts" / "init_postgres.ps1").read_text(encoding="utf-8-sig")
    assert "-O memory_admin $Database" in bootstrap
    assert "-O memory_app" not in bootstrap
    assert "memoria_permanente_v52_primary" in bootstrap


def test_runtime_domain_modules_use_public_store_connection_boundary() -> None:
    for relative in (
        "conversation_ingestion.py",
        "erasure_manager.py",
        "lifecycle_manager.py",
        "session_rotation.py",
    ):
        text = (ROOT / "src" / "memory_permanent" / relative).read_text(encoding="utf-8")
        assert ".store._connection(" not in text
        assert ".store.connection(" in text


def test_runtime_workers_do_not_extract_database_password_from_pgpass() -> None:
    ingestion = (ROOT / "scripts" / "conversation_ingestion_worker.py").read_text(encoding="utf-8-sig")
    embedding = (ROOT / "scripts" / "embedding_worker.py").read_text(encoding="utf-8-sig")
    for text in (embedding, ingestion):
        assert "password = raw.split" not in text
        assert "password=password" not in text
        assert "PGPASSFILE" in text
        assert "postgresql://memory_app@127.0.0.1:55436/" in text
    assert 'user="memory_embedding_worker"' in embedding
    assert "memory_embedding_access_contexts" in embedding
    assert "MEMORY_EMBEDDING_DISCOVERY_PGPASSFILE" in embedding
