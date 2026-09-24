from memory_permanent.api import app
from memory_permanent.session_rotation import safe_point_ready


def safe_point(**overrides):
    value = {
        "streaming_critical": False,
        "upload_unconfirmed": False,
        "non_idempotent_write_pending": False,
        "tool_call_unpersisted": False,
        "last_event_confirmed": True,
        "checkpoint_possible": True,
    }
    value.update(overrides)
    return value


def test_safe_point_requires_all_critical_conditions():
    assert safe_point_ready(safe_point()) is True
    assert safe_point_ready(safe_point(streaming_critical=True)) is False
    assert safe_point_ready(safe_point(tool_call_unpersisted=True)) is False
    assert safe_point_ready(safe_point(last_event_confirmed=False)) is False
    assert safe_point_ready(safe_point(checkpoint_possible=False)) is False


def test_session_rotation_public_routes_are_exposed():
    schema = app.openapi()
    paths = set(schema["paths"])
    required = {
        "/v1/sessions",
        "/v1/sessions/{session_id}",
        "/v1/sessions/{session_id}/resume",
        "/v1/sessions/{session_id}/bindings",
        "/v1/sessions/{session_id}/current-binding",
        "/v1/session-rotations/request",
        "/v1/session-rotations/{rotation_id}/safe-point",
        "/v1/session-rotations/{rotation_id}/prepare",
        "/v1/session-rotations/{rotation_id}/bind",
        "/v1/context-packs/{context_pack_id}",
        "/v1/session-rotations/{rotation_id}/validate",
        "/v1/session-rotations/{rotation_id}/complete",
        "/v1/session-rotations/{rotation_id}/abort",
        "/v1/session-rotations/{rotation_id}",
        "/v1/session-rotations-recovery",
    }
    assert required <= paths
