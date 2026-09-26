from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memory_permanent.backup_crypto import BackupCryptoManager, BackupKeyShredded
from memory_permanent.erasure_ledger import ExternalErasureLedger
from memory_permanent.erasure_manager import erasure_spec


def test_external_erasure_ledger_is_blinded_and_chained(tmp_path: Path):
    root = tmp_path / "ledger"
    ledger = ExternalErasureLedger(root)
    item_id = "mem-sensitive-fixture-123"
    request_id = "lcr-sensitive-fixture-456"
    raw_hash = "a" * 64
    entry = ledger.append(
        tenant_id="LEGACY", item_id=item_id, lifecycle_request_id=request_id,
        content_sha256=raw_hash, erasure_id="ler-test-001", reason_code="LEGAL_REQUEST",
        backup_cutoff_at=datetime.now(UTC),
    )
    text = (root / "ledger.jsonl").read_text(encoding="utf-8")
    assert item_id not in text
    assert request_id not in text
    assert raw_hash not in text
    assert len(entry["target_token"]) == 64
    assert len(entry["blinded_content_fingerprint"]) == 64
    assert ledger.verify()["ok"] is True
    assert ledger.find_by_request(request_id)["erasure_id"] == "ler-test-001"


def test_backup_crypto_roundtrip_and_crypto_shred(tmp_path: Path):
    source = tmp_path / "source.dump"
    source.write_bytes((b"p18-backup-fixture-" * 4096) + b"END")
    manager = BackupCryptoManager(tmp_path / "keys")
    encrypted = tmp_path / "backup.mpb"
    manifest = tmp_path / "backup.encrypted.manifest.json"
    backup_id = "p18-test-backup"
    data = manager.encrypt_dump(
        dump_path=source, encrypted_path=encrypted, manifest_path=manifest, backup_id=backup_id,
        generated_at=datetime.now(UTC) - timedelta(minutes=1), metadata={"schema": "memory-0.26.0"},
    )
    source.unlink()
    restored = tmp_path / "restored.dump"
    manager.decrypt_backup(manifest_path=manifest, output_path=restored)
    assert restored.read_bytes().endswith(b"END")
    assert data["plaintext_retained"] is False
    manager.shred_key(manifest, reason="test-erasure")
    restored.unlink()
    with pytest.raises(BackupKeyShredded):
        manager.decrypt_backup(manifest_path=manifest, output_path=restored)


def test_erasure_spec_is_fail_closed():
    spec = erasure_spec()
    assert spec["new_plaintext_backups_allowed"] is False
    assert spec["raw_item_id_in_external_ledger"] is False
    assert spec["raw_content_sha256_in_external_ledger"] is False
    assert spec["serve_traffic_requires_replay_pass"] is True
    assert spec["restore_flow"] == ["RESTORE", "MIGRATE", "ERASURE_REPLAY", "VERIFY", "SERVE_TRAFFIC"]

def test_erasure_api_contract_has_gate_replay_and_no_delete():
    from memory_permanent.api import app
    paths = app.openapi()["paths"]
    required = (
        "/v1/erasure/spec", "/v1/erasure/p18", "/v1/erasure/replay",
        "/v1/erasure/p18/close", "/v1/erasure/requests",
        "/v1/erasure/requests/{erasure_id}",
    )
    assert all(path in paths for path in required)
    assert app.version == "0.32.0"
    assert all("delete" not in {str(k).lower() for k in methods} for methods in paths.values())
