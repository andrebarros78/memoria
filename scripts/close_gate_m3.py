from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT=Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0"); sys.path.insert(0,str(ROOT/'src'))
from memory_permanent.migration_runner import migration_status  # noqa: E402
from memory_permanent.store import PostgresMemoryStore  # noqa: E402

proofs={}
for name in ['M3_TENANT_ISOLATION_PROOF','M3_SECRET_PROOF','M3_POISONING_PROOF','M3_CORRECTION_PROOF']:
 p=ROOT/'evidence'/f'{name}.json'; proofs[name]=json.loads(p.read_text(encoding='utf-8'))
with urllib.request.urlopen('http://127.0.0.1:8787/health',timeout=5) as r: health=json.loads(r.read().decode())  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
raw=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip(); host,port,db,user,pw=raw.split(':',4); dsn=f'host={host} port={port} dbname={db} user={user} password={pw} connect_timeout=5'
store=PostgresMemoryStore(dsn,initialize=False,tenant_id='__SYSTEM__'); audit=store.verify_audit_chain(); migrations=migration_status(dsn)
m6=next(x for x in migrations if x['version']=='0006_m3_tenant_rls'); migration_file=ROOT/'migrations/0006_m3_tenant_rls.sql'; file_sha=hashlib.sha256(migration_file.read_bytes()).hexdigest()
vault=ROOT/'runtime/vault'; key=vault/'.master.key'
checks={
 'API_MIN_0_6_0_HEALTHY':health.get('status')=='ok' and tuple(map(int,health.get('version','0.0.0').split('.'))) >= (0,6,0),
 'MIGRATION_0006_CHECKSUM_MATCH':m6['checksum_sha256']==file_sha,
 'TENANT_ISOLATION_PASS':proofs['M3_TENANT_ISOLATION_PROOF'].get('M3_TENANT_ISOLATION_PROOF')=='PASS',
 'SECRET_SANITIZATION_PASS':proofs['M3_SECRET_PROOF'].get('M3_SECRET_PROOF')=='PASS',
 'POISONING_PASS':proofs['M3_POISONING_PROOF'].get('M3_POISONING_PROOF')=='PASS',
 'CORRECTION_PASS':proofs['M3_CORRECTION_PROOF'].get('M3_CORRECTION_PROOF')=='PASS',
 'AUDIT_CHAIN_INTACT':bool(audit.get('ok')),
 'VAULT_MASTER_KEY_PRESENT':key.exists() and len(key.read_bytes())==32,
 'PURGE_STILL_FAIL_CLOSED':health.get('purge_direct_enabled') is False,
}
failed=[k for k,v in checks.items() if not v]
result={'generated_at':time.strftime('%Y-%m-%dT%H:%M:%S'),'gate':'M3','schema_version':health.get('version'),'migration_checksum':file_sha,'subproofs':{k:{'status':next((v for kk,v in p.items() if kk.endswith('_PROOF') and isinstance(v,str)),None),'file':f'evidence/{k}.json'} for k,p in proofs.items()},'audit':audit,'checks':checks,'failed_checks':failed,'GATE_M3':'PASS' if not failed else 'FAIL','SECURITY_PROVEN':not failed}
(ROOT/'evidence/M3_GATE_PROOF.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
lines=['# Gate M3 - Seguranca','',f"**GATE_M3:** {result['GATE_M3']}",f"**SECURITY_PROVEN:** {str(result['SECURITY_PROVEN']).lower()}",'',f"Schema: `{result['schema_version']}`",f"Migration SHA-256: `{file_sha}`",'', '## Checks']+[f"- {k}: {'PASS' if v else 'FAIL'}" for k,v in checks.items()]
(ROOT/'evidence/M3_GATE_PROOF.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'GATE_M3':result['GATE_M3'],'SECURITY_PROVEN':result['SECURITY_PROVEN'],'audit_events':audit.get('events'),'audit_head':audit.get('head'),'failed':failed},indent=2))
raise SystemExit(0 if not failed else 1)
