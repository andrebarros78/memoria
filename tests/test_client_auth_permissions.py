import pytest

from memory_permanent.client_auth import (
    required_permission_for_path,
    validate_client_id,
)


def test_memory_permissions_are_scoped_by_operation():
    assert required_permission_for_path('/v1/memories', 'GET') == 'memory:read'
    assert required_permission_for_path('/v1/memories', 'POST') == 'memory:write'
    assert required_permission_for_path('/v1/memories/mem-1/versions', 'GET') == 'memory:read'
    assert required_permission_for_path('/v1/memories/mem-1/versions', 'POST') == 'memory:write'
    assert required_permission_for_path('/v1/context/retrieve', 'POST') == 'memory:context'
    assert required_permission_for_path('/v1/checkpoints', 'POST') == 'memory:checkpoint'
    assert required_permission_for_path('/v1/leases/job/acquire', 'POST') == 'memory:lease'
    assert required_permission_for_path('/v1/memories/classify', 'POST') == 'memory:admin'
    assert required_permission_for_path('/v1/dashboard/summary', 'GET') == 'memory:admin'
    assert required_permission_for_path('/v1/purge', 'POST') == 'memory:purge'


def test_conversation_and_session_permissions_remain_separate():
    assert required_permission_for_path('/v1/conversation-ingestion/turn', 'POST') == 'conversation:ingest'
    assert required_permission_for_path('/v1/external-sessions/capture', 'POST') == 'conversation:ingest'
    assert required_permission_for_path('/v1/conversation-ingestion/pending', 'GET') == 'conversation:admin'
    assert required_permission_for_path('/v1/sessions/s-1', 'GET') == 'session:manage'
    assert required_permission_for_path('/v1/session-rotations/request', 'POST') == 'session:manage'


def test_decision_write_requires_decision_capability_not_generic_experience():
    assert required_permission_for_path('/v1/decisions', 'POST') == 'memory:decision'
    assert required_permission_for_path('/v1/decisions/decision-1', 'PATCH') == 'memory:decision'


def test_browser_session_bootstrap_requires_dedicated_capability():
    assert required_permission_for_path('/v1/auth/browser-sessions', 'POST') == 'memory:browser-session'


def test_client_id_validation_is_shared_with_credential_path_users():
    assert validate_client_id("chatgpt-capture") == "chatgpt-capture"
    for value in ("", "../escape", "bad/client", "bad\\client", "space client", "x" * 121):
        with pytest.raises(ValueError):
            validate_client_id(value)
