import pytest

from memory_permanent.api import app
from memory_permanent.client_auth import required_permission_for_path
from memory_permanent.operational_memory import (
    OPERATIONAL_MEMORY_VERSION,
    OperationalProofResult,
    OperationalProofType,
    OperationalStatus,
    normalize_operational_key,
    normalize_sha256,
    operational_memory_spec,
    validate_capability_record,
    validate_competency_record,
    validate_proof_record,
    validate_skill_version_record,
)


def test_operational_spec_exact_contract() -> None:
    spec=operational_memory_spec()
    assert spec['version']==OPERATIONAL_MEMORY_VERSION=='OM-1.0.0'
    assert spec['entities']==['COMPETENCY','SKILL','SKILL_VERSION','CAPABILITY']
    assert spec['statuses']==['PROVEN','STALE','FAILED','DEPRECATED']
    assert spec['proof_types']==['REPLAY','RECOVERY']
    assert spec['proof_results']==['PASS','FAIL']


def test_operational_enums_exact() -> None:
    assert [x.value for x in OperationalStatus]==['PROVEN','STALE','FAILED','DEPRECATED']
    assert [x.value for x in OperationalProofType]==['REPLAY','RECOVERY']
    assert [x.value for x in OperationalProofResult]==['PASS','FAIL']


def test_operational_key_normalization() -> None:
    assert normalize_operational_key('memory.context:recover','skill_key')=='MEMORY.CONTEXT:RECOVER'
    with pytest.raises(ValueError): normalize_operational_key('bad key with spaces','skill_key')


def test_competency_validation() -> None:
    value=validate_competency_record(competency_key='memory',title='Memory Operations',description='x',domain='core')
    assert value['competency_key']=='MEMORY'
    assert value['domain']=='CORE'


def test_skill_version_requires_exact_implementation_sha() -> None:
    good='a'*64
    value=validate_skill_version_record(version_label='1.0.0',implementation_version='0.22.0',implementation_sha256=good,contract={'input':'x'})
    assert value['implementation_sha256']==good
    with pytest.raises(ValueError,match='implementation_sha256'):
        validate_skill_version_record(version_label='1.0.0',implementation_version='0.22.0',implementation_sha256='bad',contract={'x':1})


def test_capability_requires_nonempty_contract() -> None:
    assert validate_capability_record(capability_key='memory.read',contract={'permission':'memory:read'})['capability_key']=='MEMORY.READ'
    with pytest.raises(ValueError,match='non-empty'):
        validate_capability_record(capability_key='memory.read',contract={})


def test_proof_requires_sha_evidence_and_known_type() -> None:
    proof=validate_proof_record(proof_type='replay',result='pass',artifact_ref='evidence/proof.json',artifact_sha256='b'*64,evidence={'checks':'10/10'})
    assert proof['proof_type']=='REPLAY' and proof['result']=='PASS'
    with pytest.raises(ValueError,match='non-empty'):
        validate_proof_record(proof_type='replay',result='pass',artifact_ref='x',artifact_sha256='b'*64,evidence={})


def test_sha_normalization_requires_lower_hex() -> None:
    assert normalize_sha256('A'*64)=='a'*64
    with pytest.raises(ValueError): normalize_sha256('z'*64)


def test_openapi_has_operational_routes_and_version() -> None:
    paths=app.openapi()['paths']
    assert app.version=='0.29.2'
    assert '/v1/operational-memory/spec' in paths
    assert '/v1/operations/competencies' in paths
    assert '/v1/operations/skills' in paths
    assert '/v1/operations/skill-versions' in paths
    assert '/v1/operations/skill-versions/{skill_version_id}/proofs' in paths
    assert '/v1/operations/catalog' in paths


def test_operational_auth_boundary() -> None:
    assert required_permission_for_path('/v1/operational-memory/spec','GET')=='memory:read'
    assert required_permission_for_path('/v1/operations/catalog','GET')=='memory:read'
    assert required_permission_for_path('/v1/operations/competencies','POST')=='memory:operational'


def test_proven_gate_requires_both_proof_types_in_spec() -> None:
    assert operational_memory_spec()['proven_gate']['required']==['REPLAY:PASS','RECOVERY:PASS']


def test_deprecated_documented_as_terminal() -> None:
    assert 'terminal' in operational_memory_spec()['status_rules']['DEPRECATED'].lower()
