from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_authenticated_request_store_never_runs_migrations():
    text=(ROOT/"src/memory_permanent/request_context.py").read_text(encoding="utf-8")
    assert "PostgresMemoryStore(dsn" in text
    assert "initialize=False" in text


def test_windows_runtime_launchers_never_use_postgres_superuser():
    launchers=[
        ROOT/"deploy/v5.2-primary/start-primary-v52.ps1",
        ROOT/"deploy/v5.2-rc1/start-api.ps1",
        ROOT/"deploy/v5.2-primary/start-v4-rollback.ps1",
    ]
    for path in launchers:
        text=path.read_text(encoding="utf-8-sig")
        assert "postgresql://postgres@" not in text
        assert "postgresql://memory_app@127.0.0.1:55436/" in text
        assert "PGPASSFILE" in text
        assert "pgpass.conf" in text
