from __future__ import annotations

import json
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import time
import uuid
from pathlib import Path

import psycopg

from memory_permanent.signed_client import SignedMemoryClient

ROOT=Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0")
API='http://127.0.0.1:8787'
PYTHON=ROOT/'.venv/Scripts/python.exe'
CLIENT=SignedMemoryClient(API,'local-admin')

def req(method,path,tenant,payload=None):
    st,b=CLIENT.request(method,path,payload,extra_headers={'Accept':'application/json','X-Memory-Tenant':tenant},timeout=120)
    if st>=400:
        raise RuntimeError(f'HTTP {st}: {b}')
    return st,b

def create(tenant,ns,key,text):
    p={'namespace':ns,'memory_key':key,'category':'EVIDENCE','content':{'gate':'M3','text':text,'tenant':tenant},'content_text':text,'provenance':{'trusted':True,'proof':'M3_ISOLATION_RETEST'},'confidence':1.0,'source':'sovereign-system','source_version':'M3-HARDENED','tags':['M3','ISOLATION','AUTH_HARDENED'],'changed_by':'prove_m3_isolation'}
    return req('POST','/v1/memories',tenant,p)[1]['item_id']

suffix=uuid.uuid4().hex[:12].upper()
ta='TENANT_A_'+suffix
tb='TENANT_B_'+suffix
ns='M3_ISOLATION_'+suffix
text='A sessao autenticada deve ser renovada automaticamente quando sua validade termina.'
a=create(ta,ns,'same-semantic',text)
b=create(tb,ns,'same-semantic',text)
worker=subprocess.run([str(PYTHON),str(ROOT/'scripts/embedding_worker.py'),'--limit','500'],cwd=str(ROOT),capture_output=True,text=True,timeout=240)  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.
query='Como renovar automaticamente uma sessao depois que a validade expira?'
ca=req('POST','/v1/context/retrieve',ta,{'query':query,'namespaces':[ns],'limit':5})[1]
cb=req('POST','/v1/context/retrieve',tb,{'query':query,'namespaces':[ns],'limit':5})[1]
la=req('GET','/v1/memories?limit=500',ta)[1]
lb=req('GET','/v1/memories?limit=500',tb)[1]
ida={str(x.get('item_id')) for x in ca.get('selected',[])}
idb={str(x.get('item_id')) for x in cb.get('selected',[])}
lista={str(x.get('item_id')) for x in la.get('items',[])}
listb={str(x.get('item_id')) for x in lb.get('items',[])}
raw=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip()
host,port,db,user,pw=raw.split(':',4)
dsn=f'host={host} port={port} dbname={db} user={user} password={pw} connect_timeout=5'
with psycopg.connect(dsn) as conn:
    conn.execute("SELECT set_config('app.current_tenant', %s, true)",(ta,))
    db_a=conn.execute('SELECT item_id,tenant_id FROM memory_items WHERE item_id IN (%s,%s)',(a,b)).fetchall()
with psycopg.connect(dsn) as conn:
    conn.execute("SELECT set_config('app.current_tenant', %s, true)",(tb,))
    db_b=conn.execute('SELECT item_id,tenant_id FROM memory_items WHERE item_id IN (%s,%s)',(a,b)).fetchall()
with psycopg.connect(dsn) as conn:
    policies=conn.execute("SELECT count(*) FROM pg_policies WHERE policyname='tenant_isolation'").fetchone()[0]
    forced=conn.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relrowsecurity AND c.relforcerowsecurity").fetchone()[0]
checks={
    'SIGNED_API_USED':True,
    'RLS_POLICIES_MIN_14':policies>=14,
    'FORCE_RLS_MIN_14':forced>=14,
    'TENANT_A_RETRIEVES_OWN':a in ida,
    'TENANT_A_NEVER_RETRIEVES_B':b not in ida,
    'TENANT_B_RETRIEVES_OWN':b in idb,
    'TENANT_B_NEVER_RETRIEVES_A':a not in idb,
    'TENANT_A_LIST_ISOLATED':a in lista and b not in lista,
    'TENANT_B_LIST_ISOLATED':b in listb and a not in listb,
    'DB_RLS_A_ONLY':len(db_a)==1 and str(db_a[0][0])==a and str(db_a[0][1])==ta,
    'DB_RLS_B_ONLY':len(db_b)==1 and str(db_b[0][0])==b and str(db_b[0][1])==tb,
    'SEMANTIC_MODE_A':'SEMANTIC' in set(ca.get('retrieval_modes') or []),
    'SEMANTIC_MODE_B':'SEMANTIC' in set(cb.get('retrieval_modes') or []),
    'WORKER_OK':worker.returncode==0,
}
failed=[k for k,v in checks.items() if not v]
result={'generated_at':time.strftime('%Y-%m-%dT%H:%M:%S'),'gate':'M3','proof':'TENANT_RLS_ISOLATION_AUTH_HARDENED','tenant_a':ta,'tenant_b':tb,'item_a':a,'item_b':b,'trace_a':ca.get('trace_id'),'trace_b':cb.get('trace_id'),'rls_policies':policies,'force_rls_tables':forced,'checks':checks,'failed_checks':failed,'M3_TENANT_ISOLATION_PROOF':'PASS' if not failed else 'FAIL'}
(ROOT/'evidence/M3_TENANT_ISOLATION_PROOF.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({'result':result['M3_TENANT_ISOLATION_PROOF'],'failed':failed,'rls_policies':policies,'force_rls':forced},indent=2))
raise SystemExit(0 if not failed else 1)
