from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

import psycopg

from memory_permanent.secret_sanitizer import LocalEncryptedVault, default_vault_root
from memory_permanent.signed_client import SignedMemoryClient

ROOT=Path(r"C:\New Projet\MEMORIA-PERMANENTE")
API='http://127.0.0.1:8787'
CLIENT=SignedMemoryClient(API,'local-admin')
suffix=uuid.uuid4().hex
tenant='TENANT_SECRET_'+suffix[:10].upper()
namespace='M3_SECRET_'+suffix[:10].upper()
secret='m3-proof-token-'+uuid.uuid4().hex+uuid.uuid4().hex
secret_sha=hashlib.sha256(secret.encode()).hexdigest()
text=f'Authorization: Bearer {secret} must never become textual memory.'
payload={'namespace':namespace,'memory_key':'secret-sanitization','category':'EVIDENCE','content':{'header':f'Authorization: Bearer {secret}','note':'credential is referenced only'},'content_text':text,'provenance':{'trusted':True,'proof':'M3_SECRET_AUTH_HARDENED'},'confidence':1.0,'source':'sovereign-system','source_version':'M3-HARDENED','tags':['M3','SECRET','DPAPI'],'changed_by':'prove_m3_secret'}
st,item=CLIENT.request('POST','/v1/memories',payload,extra_headers={'Accept':'application/json','X-Memory-Tenant':tenant,'Idempotency-Key':'m3-secret-'+suffix},timeout=60)
if st!=201:
    raise RuntimeError(f'create failed {st} {item}')
item_id=item['item_id']
raw=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip()
host,port,db,user,pw=raw.split(':',4)
dsn=f'host={host} port={port} dbname={db} user={user} password={pw} connect_timeout=5'
with psycopg.connect(dsn) as conn:
    conn.execute("SELECT set_config('app.current_tenant', %s, true)",(tenant,))
    m=conn.execute('SELECT content_text,content_json,provenance FROM memory_items WHERE item_id=%s',(item_id,)).fetchone()
    versions=conn.execute('SELECT content_text,content_json,provenance FROM memory_versions WHERE item_id=%s',(item_id,)).fetchall()
with psycopg.connect(dsn) as conn:
    conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',true)")
    audits=conn.execute('SELECT payload::text FROM audit_events WHERE target_id=%s',(item_id,)).fetchall()
blob='\n'.join([str(m[0]),json.dumps(m[1]),json.dumps(m[2])]+[str(x) for row in versions for x in row]+[str(x[0]) for x in audits])
refs=list((m[2] or {}).get('secret_refs') or [])
ref=refs[0] if refs else ''
vault_root=default_vault_root()
vault=LocalEncryptedVault(vault_root)
recovered=vault.get(ref) if ref else ''
vault_files=list(vault_root.glob('*.json'))
vault_plaintext_found=any(secret in p.read_text(encoding='utf-8') for p in vault_files)
dpapi=vault_root/'vault-master.dpapi'
legacy_key=ROOT/'runtime/vault/.master.key'
legacy_root=ROOT/'runtime/vault'
checks={
    'SIGNED_API_USED':True,
    'SECRET_NOT_IN_CANONICAL_DB':secret not in blob,
    'SECRET_REF_PRESENT':bool(ref) and ref.startswith('vault://memory/'),
    'PROVENANCE_MARKED_SANITIZED':bool((m[2] or {}).get('secret_sanitized')),
    'CONTENT_TEXT_REPLACED':secret not in str(m[0]) and ref in str(m[0]),
    'CONTENT_JSON_REPLACED':secret not in json.dumps(m[1]) and ref in json.dumps(m[1]),
    'ALL_VERSIONS_SANITIZED':all(secret not in str(x) for row in versions for x in row),
    'AUDIT_SANITIZED':all(secret not in str(x[0]) for x in audits),
    'VAULT_DECRYPTS_EXACT_SECRET':recovered==secret,
    'VAULT_FILE_NOT_PLAINTEXT':not vault_plaintext_found,
    'VAULT_OUTSIDE_PRODUCT_TREE':ROOT.resolve() not in vault_root.resolve().parents and vault_root.resolve()!=ROOT.resolve(),
    'DPAPI_KEY_BLOB_PRESENT':dpapi.exists() and dpapi.stat().st_size>32,
    'DPAPI_KEY_NOT_RAW_32_BYTES':dpapi.exists() and dpapi.stat().st_size!=32,
    'LEGACY_PLAINTEXT_MASTER_KEY_ABSENT':not legacy_key.exists(),
    'LEGACY_VAULT_TREE_ABSENT':not legacy_root.exists(),
}
failed=[k for k,v in checks.items() if not v]
result={'generated_at':time.strftime('%Y-%m-%dT%H:%M:%S'),'gate':'M3','proof':'SECRET_SANITIZATION_DPAPI','tenant':tenant,'item_id':item_id,'secret_sha256':secret_sha,'secret_ref':ref,'vault_file_count':len(vault_files),'vault_root':str(vault_root),'dpapi_blob_bytes':dpapi.stat().st_size if dpapi.exists() else 0,'checks':checks,'failed_checks':failed,'M3_SECRET_PROOF':'PASS' if not failed else 'FAIL'}
(ROOT/'evidence/M3_SECRET_PROOF.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({'result':result['M3_SECRET_PROOF'],'item_id':item_id,'secret_ref':ref,'secret_sha256':secret_sha,'dpapi_blob_bytes':result['dpapi_blob_bytes'],'failed':failed},indent=2))
raise SystemExit(0 if not failed else 1)
