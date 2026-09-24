import hashlib
import json

from memory_permanent.recovery_integrity_agent import RecoveryIntegrityAgent


def test_recovery_integrity_agent_verifies_manifest_and_all_gates(tmp_path):
    artifact=tmp_path/'artifact.bin'; artifact.write_bytes(b'proof')
    digest=hashlib.sha256(b'proof').hexdigest()
    manifest=tmp_path/'manifest.json'; manifest.write_text(json.dumps({'artifacts':[{'path':'artifact.bin','sha256':digest}]}),encoding='utf-8')
    agent=RecoveryIntegrityAgent()
    m=agent.verify_manifest(manifest)
    assert m.passed is True
    report=agent.assess(pg_amcheck_exit=0,restore_exit=0,regression_exit=0,security_scan_exit=0,manifest_check=m)
    assert report.passed is True


def test_recovery_integrity_agent_fails_closed_on_hash_or_gate(tmp_path):
    artifact=tmp_path/'artifact.bin'; artifact.write_bytes(b'changed')
    manifest=tmp_path/'manifest.json'; manifest.write_text(json.dumps({'artifacts':[{'path':'artifact.bin','sha256':'0'*64}]}),encoding='utf-8')
    agent=RecoveryIntegrityAgent(); m=agent.verify_manifest(manifest)
    assert m.passed is False
    report=agent.assess(pg_amcheck_exit=0,restore_exit=1,regression_exit=0,security_scan_exit=0,manifest_check=m)
    assert report.passed is False
