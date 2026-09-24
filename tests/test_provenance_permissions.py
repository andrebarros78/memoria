from memory_permanent.client_auth import ClientPrincipal
from memory_permanent.provenance_policy import derive_authenticated_provenance


def _principal(permissions):
    return ClientPrincipal(
        client_id="client-a", permissions=frozenset(permissions), tenants=frozenset({"TENANT_A"}),
        agents=frozenset(), users=frozenset(), projects=frozenset(), teams=frozenset(), organizations=frozenset(),
        default_tenant="TENANT_A",
    )


def test_provenance_attestation_requires_explicit_capability():
    _, provenance = derive_authenticated_provenance(
        _principal({"memory:write", "provenance:attest"}), asserted_source="caller", asserted_provenance={"trusted": False}
    )
    assert provenance["trusted"] is True
    assert provenance["trust"]["basis"] == "AUTHENTICATED_CAPABILITY"


def test_wildcards_do_not_implicitly_attest_provenance():
    for permissions in ({"provenance:*"}, {"*"}, {"memory:write"}):
        _, provenance = derive_authenticated_provenance(
            _principal(permissions), asserted_source="human", asserted_provenance={"trusted": True}
        )
        assert provenance["trusted"] is False
