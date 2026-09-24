from memory_permanent.session_rotation import normalize_external_session_ref
from memory_permanent.session_rotation_api import router


def test_normalize_chatgpt_project_path():
    value = normalize_external_session_ref(
        "chatgpt",
        "g/g-p-6a578ce6aa288191bbcff02977902818/c/6a8f92e7-1e24-83e9-805e-af7360009344",
    )
    assert value["canonical_external_ref"] == "6a8f92e7-1e24-83e9-805e-af7360009344"
    assert value["external_project_ref"] == "g/g-p-6a578ce6aa288191bbcff02977902818"


def test_normalize_chatgpt_bare_id():
    value = normalize_external_session_ref("chatgpt", "6a8f92e7-1e24-83e9-805e-af7360009344")
    assert value["canonical_external_ref"] == "6a8f92e7-1e24-83e9-805e-af7360009344"
    assert value["external_project_ref"] is None


def test_reverse_resolver_route_registered():
    assert "/v1/external-sessions/resolve" in {getattr(route, "path", None) for route in router.routes}




def test_capture_and_recover_routes_registered():
    paths = {getattr(route, "path", None) for route in router.routes}
    assert "/v1/external-sessions/capture" in paths
    assert "/v1/conversations/recover" in paths
