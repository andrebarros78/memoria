from pathlib import Path

from memory_permanent.api import app
from memory_permanent.client_auth import is_public_path, required_permission_for_path

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'src'/'memory_permanent'


def test_legacy_governor_route_is_not_public_or_mounted() -> None:
    assert is_public_path('/v1/governor/contract') is False
    assert is_public_path('/openapi.json') is False
    assert is_public_path('/docs') is False
    assert is_public_path('/redoc') is False
    paths={getattr(route,'path',None) for route in app.routes}
    assert not any(str(path).startswith('/v1/governor') for path in paths if path)


def test_governor_specific_auth_headers_are_absent_from_active_source() -> None:
    findings=[]
    for path in SRC.glob('*.py'):
        text=path.read_text(encoding='utf-8-sig')
        if 'X-Governor-Key' in text or '/v1/governor' in text:
            findings.append(path.name)
    assert findings == []


def test_derived_artifact_reads_use_normal_memory_capability() -> None:
    assert required_permission_for_path('/v1/derived-artifacts','GET') == 'memory:read'
    assert required_permission_for_path('/v1/derived-artifacts/art-1/dependencies','GET') == 'memory:read'
