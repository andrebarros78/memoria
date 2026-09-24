from pathlib import Path

from memory_permanent.secret_sanitizer import (
    platform_key_reference,
    platform_protected_key_path,
)


def test_windows_key_names_remain_dpapi_compatible():
    root=Path(r"C:/ProgramData/MemoriaPermanente/vault")
    assert platform_protected_key_path(root,"vault-master",platform_name="nt").name == "vault-master.dpapi"
    assert platform_protected_key_path(root,"local-admin",platform_name="nt").name == "local-admin.dpapi"
    assert platform_key_reference("backup-keys","backup-1",platform_name="nt") == "dpapi://backup-keys/backup-1"


def test_posix_key_names_are_separate_from_windows_format():
    root=Path("/var/lib/memoria-permanente/vault")
    assert platform_protected_key_path(root,"vault-master",platform_name="posix").name == "vault-master.key"
    assert platform_key_reference("backup-keys","backup-1",platform_name="posix") == "posix-wrapped://backup-keys/backup-1"
