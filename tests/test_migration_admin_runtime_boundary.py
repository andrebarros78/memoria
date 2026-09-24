from pathlib import Path

import pytest

from memory_permanent.runtime_preflight import verify_migration_parity

ROOT=Path(__file__).resolve().parents[1]


def test_runtime_preflight_accepts_exact_migration_hash_parity():
    expected={"0001_base":"a"*64,"0002_next":"b"*64}
    applied=[{"version":k,"checksum_sha256":v} for k,v in expected.items()]
    result=verify_migration_parity(applied,expected)
    assert result["migration_count"] == 2
    assert result["latest_migration"] == "0002_next"


@pytest.mark.parametrize("applied", [
    [{"version":"0001_base","checksum_sha256":"a"*64}],
    [{"version":"0001_base","checksum_sha256":"c"*64},{"version":"0002_next","checksum_sha256":"b"*64}],
    [{"version":"0001_base","checksum_sha256":"a"*64},{"version":"0002_next","checksum_sha256":"b"*64},{"version":"9999_extra","checksum_sha256":"d"*64}],
])
def test_runtime_preflight_fails_closed_on_missing_drift_or_extra(applied):
    expected={"0001_base":"a"*64,"0002_next":"b"*64}
    with pytest.raises(RuntimeError, match="migration parity failed"):
        verify_migration_parity(applied,expected)


def test_runtime_and_admin_migration_paths_are_separated():
    deprecated=(ROOT/"scripts/apply_pending_migrations_app.py").read_text(encoding="utf-8")
    admin=(ROOT/"scripts/apply_pending_migrations_admin.py").read_text(encoding="utf-8")
    assert "DEPRECATED_FAIL_CLOSED" in deprecated
    assert "MEMORY_ADMIN_DATABASE_URL" in admin
    assert 'str(row[0]) != "postgres"' in admin
    assert "rolsuper" in admin
    assert "parsed.password is not None" in admin
    assert "postgres_admin.pw" not in admin
    assert "memory_app" not in admin
    for rel in ["deploy/v5.2-primary/start-primary-v52.ps1","deploy/v5.2-rc1/start-api.ps1"]:
        text=(ROOT/rel).read_text(encoding="utf-8-sig")
        assert "runtime_preflight.py" in text
        assert text.index("runtime_preflight.py") < text.index("Start-Process")
