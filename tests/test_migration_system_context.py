from pathlib import Path


def test_migration_runner_sets_system_tenant_for_force_rls() -> None:
    root=Path(__file__).resolve().parents[1]
    text=(root/'src/memory_permanent/migration_runner.py').read_text(encoding='utf-8')
    assert "set_config('app.current_tenant','__SYSTEM__',true)" in text
    assert text.count('_set_system_tenant(conn)') >= 2


def test_legacy_governor_auth_source_is_removed() -> None:
    root=Path(__file__).resolve().parents[1]
    source='\n'.join(p.read_text(encoding='utf-8-sig') for p in (root/'src/memory_permanent').glob('*.py'))
    assert 'X-Governor-Key' not in source
    assert '/v1/governor/' not in source
