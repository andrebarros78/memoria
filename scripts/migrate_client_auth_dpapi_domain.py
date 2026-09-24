from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT=Path(r"C:\New Projet\MEMORIA-PERMANENTE")
PROGRAM_DATA=Path(os.environ.get('ProgramData',r'C:\ProgramData'))
AUTH_ROOT=PROGRAM_DATA/'MemoriaPermanente'/'auth'
REGISTRY=AUTH_ROOT/'clients.json'
BACKUP=AUTH_ROOT/'pre-client-auth-domain-v2'
GOV_MIRROR=PROGRAM_DATA/'GovernorWindows'/'memory-auth'/'governor-runtime.dpapi'

import sys  # noqa: E402

sys.path.insert(0,str(ROOT/'src'))
from memory_permanent.client_auth import CLIENT_AUTH_ENTROPY  # noqa: E402
from memory_permanent.secret_sanitizer import WindowsDpapiKeyProvider  # noqa: E402

VAULT_ENTROPY=b'MEMORIA-PERMANENTE:VAULT:V1'

def decrypt_existing(path: Path) -> tuple[bytes,str]:
    try:
        return WindowsDpapiKeyProvider(path,machine_scope=True,entropy=CLIENT_AUTH_ENTROPY).load_or_create(),'CLIENT-AUTH'
    except (OSError, RuntimeError, ValueError):
        return WindowsDpapiKeyProvider(path,machine_scope=True,entropy=VAULT_ENTROPY).load_or_create(),'VAULT-LEGACY'

def main()->int:
    data=json.loads(REGISTRY.read_text(encoding='utf-8'))
    BACKUP.mkdir(parents=True,exist_ok=True)
    proofs=[]
    governor_secret=None
    for client_id,row in sorted(data['clients'].items()):
        path=(AUTH_ROOT/str(row['secret_file'])).resolve()
        shutil.copy2(path,BACKUP/path.name)
        secret,old_domain=decrypt_existing(path)
        WindowsDpapiKeyProvider(path,machine_scope=True,entropy=CLIENT_AUTH_ENTROPY).protect_existing(secret)
        verify=WindowsDpapiKeyProvider(path,machine_scope=True,entropy=CLIENT_AUTH_ENTROPY).load_or_create()
        if verify!=secret:
            raise RuntimeError(f'auth migration verification failed: {client_id}')
        if client_id=='governor-runtime': governor_secret=secret
        proofs.append({'client_id':client_id,'old_domain':old_domain,'new_domain':'CLIENT-AUTH','blob_bytes':path.stat().st_size,'secret_preserved':True})  # nosec B105 -- boolean evidence/status field, not a credential.
    if governor_secret is not None:
        GOV_MIRROR.parent.mkdir(parents=True,exist_ok=True)
        WindowsDpapiKeyProvider(GOV_MIRROR,machine_scope=True,entropy=CLIENT_AUTH_ENTROPY).protect_existing(governor_secret)
        if WindowsDpapiKeyProvider(GOV_MIRROR,machine_scope=True,entropy=CLIENT_AUTH_ENTROPY).load_or_create()!=governor_secret:
            raise RuntimeError('consumer mirror verification failed')
    proof={'domain':'CLIENT-AUTH','backup_dir':str(BACKUP),'clients':proofs,'consumer_mirror_updated':governor_secret is not None,'PASS':True}  # nosec B105 -- boolean evidence/status field, not a credential.
    (ROOT/'evidence/CLIENT_AUTH_DPAPI_DOMAIN_MIGRATION_PROOF.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    print(json.dumps({'clients':len(proofs),'legacy_migrated':sum(x['old_domain']=='VAULT-LEGACY' for x in proofs),'consumer_mirror_updated':proof['consumer_mirror_updated'],'PASS':True},indent=2))  # nosec B105 -- boolean evidence/status field, not a credential.
    return 0

if __name__=='__main__': raise SystemExit(main())
