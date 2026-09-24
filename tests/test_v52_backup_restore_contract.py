from pathlib import Path

from memory_permanent.backup_crypto import safe_manifest_metadata

ROOT=Path(__file__).resolve().parents[1]

def test_backup_is_encrypted_acl_preserving_and_never_reads_password_material():
    text=(ROOT/'scripts/backup_memory_v52.py').read_text(encoding='utf-8')
    assert 'PGPASSFILE' in text and 'pg_dump' in text and 'BackupCryptoManager' in text
    assert '"-Fc"' in text
    assert '--no-acl' not in text and '--no-privileges' not in text and '--no-owner' not in text
    assert 'env["PGPASSWORD"]' not in text and "os.getenv('PGPASSWORD'" not in text and 'password={' not in text
    assert 'dump.unlink(missing_ok=True)' in text
    assert 'plaintext_retained' in text

def test_restore_is_fixed_target_acl_preserving_amcheck_and_erasure_replay():
    text=(ROOT/'scripts/prove_v52_encrypted_restore.py').read_text(encoding='utf-8')
    assert 'TARGET = "memoria_permanente_v52_restoreproof"' in text
    assert 'pg_amcheck' in text and 'apply_migrations' in text and 'verify_runtime_database' in text and 'verify_audit_chain' in text
    assert 'ErasureManager(store).replay' in text
    assert '--no-acl' not in text and '--no-privileges' not in text and 'PGPASSWORD' not in text
    assert 'tmp.unlink(missing_ok=True)' in text

def test_backup_manifest_allows_security_metadata_without_arbitrary_keys():
    clean=safe_manifest_metadata({'database':'x','acl_preserved':True,'owner_preserved':True,'postgresql':'18.6','pgvector':'0.8.6','migration_count':44,'latest_migration':'0044_x'})
    assert clean['acl_preserved'] is True and clean['migration_count']==44
