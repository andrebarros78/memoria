from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_postgres_credential_provisioner_never_embeds_static_secret():
    text=(ROOT/"scripts/provision_postgres_runtime_credentials.ps1").read_text(encoding="utf-8-sig")
    assert "RandomNumberGenerator" in text
    assert ".GetBytes($bytes)" in text
    assert "BitConverter" in text
    assert "SECRET_MATERIAL_EXPOSED=FALSE" in text
    assert "ALTER ROLE memory_app LOGIN PASSWORD" in text
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS" in text
    assert "postgres.pgpass.conf" in text
    assert "icacls" in text
    assert "*S-1-5-18" in text
    assert ".pre-hardening-" not in text
    assert "Write-Output $appPw" not in text and "Write-Output $adminPw" not in text


def test_hba_hardener_is_separate_fail_safe_scram_transition():
    text=(ROOT/"scripts/harden_pg_hba.ps1").read_text(encoding="utf-8-sig")
    assert "memory-app-runtime-proven.json" in text
    assert "scram-sha-256" in text
    assert "auth_method='trust'" in text
    assert "Copy-Item -LiteralPath $Backup -Destination $Hba" in text
    assert "PG_HBA_SCRAM=PROVEN" in text


def test_admin_migration_path_uses_pgpass_and_loopback_nonsecret_dsn():
    ps=(ROOT/"scripts/apply_pending_migrations_admin.ps1").read_text(encoding="utf-8-sig")
    py=(ROOT/"scripts/apply_pending_migrations_admin.py").read_text(encoding="utf-8")
    assert "postgres.pgpass.conf" in ps
    assert "postgresql://postgres@127.0.0.1:55436/" in ps
    assert "password" not in ps.lower().replace("pgpass","pg-pass")
    assert "parsed.password is not None" in py
    assert "current_user" in py and "rolsuper" in py
