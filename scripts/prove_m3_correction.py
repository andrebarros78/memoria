from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import psycopg

from memory_permanent.signed_client import SignedMemoryClient

ROOT=Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0")
API='http://127.0.0.1:8787'
CLIENT=SignedMemoryClient(API,'local-admin')
suffix=uuid.uuid4().hex[:10].upper()
tenant='TENANT_CORRECTION_'+suffix
ns='M3_CORRECTION_'+suffix

def req(method,path,payload=None,extra=None):
    h={'Accept':'application/json','X-Memory-Tenant':tenant}
    h.update(extra or {})
    st,b=CLIENT.request(method,path,payload,extra_headers=h,timeout=60)
    if st>=400:
        raise RuntimeError(f'HTTP {st}: {b}')
    return b

create={'namespace':ns,'memory_key':'feature-state','category':'FACT','content':{'state':'A','value':'desligado'},'content_text':'Estado da funcionalidade: desligado.','provenance':{'trusted':True,'proof':'M3_CORRECTION_AUTH_HARDENED','observation':'A'},'confidence':1.0,'source':'human','source_version':'M3-HARDENED','tags':['M3','CORRECTION'],'changed_by':'prove_m3_correction'}
item=req('POST','/v1/memories',create,{'Idempotency-Key':'m3-correct-create-'+suffix})['item_id']
before=req('GET',f'/v1/memories/{item}/versions')
time.sleep(0.6)
revision={'content':{'state':'B','value':'ligado'},'content_text':'Correcao confirmada: estado da funcionalidade agora e ligado.','provenance':{'trusted':True,'proof':'M3_CORRECTION_AUTH_HARDENED','observation':'B','corrects':'A'},'confidence':1.0,'source':'human','source_version':'M3-HARDENED','tags':['M3','CORRECTION','CORRECTED'],'changed_by':'prove_m3_correction'}
rev=req('POST',f'/v1/memories/{item}/versions',revision,{'Idempotency-Key':'m3-correct-revise-'+suffix})
after=req('GET',f'/v1/memories/{item}/versions')
versions=after.get('versions') or []
raw=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip()
host,port,db,user,pw=raw.split(':',4)
dsn=f'host={host} port={port} dbname={db} user={user} password={pw} connect_timeout=5'
with psycopg.connect(dsn) as conn:
    conn.execute("SELECT set_config('app.current_tenant', %s, true)",(tenant,))
    current=conn.execute('SELECT content_json,content_text,content_sha256 FROM memory_items WHERE item_id=%s',(item,)).fetchone()
    events=conn.execute("SELECT event_type FROM memory_events WHERE item_id=%s ORDER BY event_seq",(item,)).fetchall()
append_only_blocked=False
try:
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT set_config('app.current_tenant', %s, true)",(tenant,))
        conn.execute("UPDATE memory_versions SET content_text='tamper' WHERE item_id=%s AND version_no=1",(item,))
        conn.commit()
except psycopg.Error:
    append_only_blocked=True
v1=versions[0] if len(versions)>0 else {}
v2=versions[1] if len(versions)>1 else {}
before_v1=(before.get('versions') or [{}])[0]
checks={
    'SIGNED_API_USED':True,
    'TWO_VERSIONS_PRESENT':len(versions)==2,
    'VERSION_NUMBERS_1_2':[v.get('version_no') for v in versions]==[1,2],
    'V1_CONTENT_A':(v1.get('content_json') or {}).get('state')=='A',
    'V2_CONTENT_B':(v2.get('content_json') or {}).get('state')=='B',
    'CURRENT_IS_B':current is not None and (current[0] or {}).get('state')=='B',
    'V2_LINKS_V1':v2.get('previous_version_id')==v1.get('version_id'),
    'V1_IMMUTABLE_HASH':before_v1.get('content_sha256')==v1.get('content_sha256') and before_v1.get('version_id')==v1.get('version_id'),
    'TEMPORAL_VALID_FROM':bool(v1.get('valid_from')) and bool(v2.get('valid_from')),
    'V1_VALID_UNTIL_EQUALS_V2_VALID_FROM':v1.get('valid_until')==v2.get('valid_from'),
    'V2_CURRENT_OPEN_ENDED':v2.get('valid_until') is None,
    'CREATE_AND_REVISE_EVENTS':[x[0] for x in events][-2:]==['MEMORY_CREATED','MEMORY_REVISED'],
    'APPEND_ONLY_UPDATE_BLOCKED':append_only_blocked,
    'REVISION_RESPONSE_V2':int(rev.get('version_no') or 0)==2,
}
failed=[k for k,v in checks.items() if not v]
result={'generated_at':time.strftime('%Y-%m-%dT%H:%M:%S'),'gate':'M3','proof':'CORRECTION_VERSIONING_AUTH_HARDENED','tenant':tenant,'item_id':item,'version_1':{'id':v1.get('version_id'),'valid_from':v1.get('valid_from'),'valid_until':v1.get('valid_until'),'sha256':v1.get('content_sha256')},'version_2':{'id':v2.get('version_id'),'valid_from':v2.get('valid_from'),'valid_until':v2.get('valid_until'),'sha256':v2.get('content_sha256')},'checks':checks,'failed_checks':failed,'M3_CORRECTION_PROOF':'PASS' if not failed else 'FAIL'}
(ROOT/'evidence/M3_CORRECTION_PROOF.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({'result':result['M3_CORRECTION_PROOF'],'failed':failed},indent=2))
raise SystemExit(0 if not failed else 1)
