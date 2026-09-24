from memory_permanent.client_auth import ClientPrincipal
from memory_permanent.provenance_policy import (
    derive_authenticated_provenance,
    is_system_assigned_trust,
)


def principal(permissions):
    return ClientPrincipal(
        client_id='writer-a', permissions=frozenset(permissions), tenants=frozenset({'TENANT'}),
        agents=frozenset(), users=frozenset(), projects=frozenset(), teams=frozenset(), organizations=frozenset(),
        default_tenant='TENANT',
    )


def test_wildcard_does_not_implicitly_attest_provenance():
    source, provenance = derive_authenticated_provenance(
        principal({'*'}), asserted_source='sovereign-system', asserted_provenance={'trusted': True}
    )
    assert source == 'authenticated-client:writer-a'
    assert provenance['trusted'] is False
    assert provenance['asserted_source'] == 'sovereign-system'
    assert is_system_assigned_trust(provenance) is False


def test_explicit_attestation_capability_assigns_trust():
    _, provenance = derive_authenticated_provenance(
        principal({'memory:write','provenance:attest'}), asserted_source='human', asserted_provenance={}
    )
    assert provenance['trusted'] is True
    assert is_system_assigned_trust(provenance) is True
