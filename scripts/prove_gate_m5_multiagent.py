from __future__ import annotations

import concurrent.futures
import json
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import psycopg

from memory_permanent.signed_client import SignedMemoryClient

ROOT=Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0"); API='http://127.0.0.1:8787'
suffix=uuid.uuid4().hex[:10].upper(); tenant='TENANT_M5_'+suffix; ns='M5_MULTIAGENT_'+suffix
A={'X-Memory-Tenant':tenant,'X-Memory-Agent':'agent-a','X-Memory-User':'user-a','X-Memory-Project':'project-1','X-Memory-Team':'team-1','X-Memory-Organization':'org-1'}
B={'X-Memory-Tenant':tenant,'X-Memory-Agent':'agent-b','X-Memory-User':'user-b','X-Memory-Project':'project-1','X-Memory-Team':'team-1','X-Memory-Organization':'org-1'}
C={'X-Memory-Tenant':tenant,'X-Memory-Agent':'agent-c','X-Memory-User':'user-c','X-Memory-Project':'project-2','X-Memory-Team':'team-2','X-Memory-Organization':'org-2'}

def request(method,path,headers,payload=None,timeout=90):
    client=SignedMemoryClient(API,'local-admin')
    h={'Accept':'application/json',**headers}
    return client.request(method,path,payload,extra_headers=h,timeout=timeout)
def create(scope,key,token):
    p={'namespace':ns,'memory_key':key,'category':'EVIDENCE','content':{'gate':'M5','scope':scope,'token':token},'content_text':f'Multiagent visibility proof {token}','provenance':{'trusted':True,'proof':'M5_MULTIAGENT'},'confidence':1.0,'source':'sovereign-system','source_version':'M5','tags':['M5','MULTIAGENT',scope],'changed_by':'prove_gate_m5','sharing_scope':scope}
    h={**A,'Idempotency-Key':'m5-'+key+'-'+suffix}
    st,b=request('POST','/v1/memories',h,p)
    if st!=201: raise RuntimeError(f'create {scope} failed {st} {b}')
    return b['item_id']

def listed(actor,token):
    q=urllib.parse.urlencode({'q':token,'limit':50})
    st,b=request('GET','/v1/memories?'+q,actor)
    return st,{str(x.get('item_id')) for x in b.get('items',[])}

def context_ids(actor,query):
    st,b=request('POST','/v1/context/retrieve',actor,{'query':query,'namespaces':[ns],'limit':12})
    return st,{str(x.get('item_id')) for x in b.get('selected',[])},b

scopes={
 'AGENT_PRIVATE':'TOK_AGENT_'+suffix,
 'AGENT_TEAM':'TOK_TEAM_'+suffix,
 'PROJECT_SHARED':'TOK_PROJECT_'+suffix,
 'ORGANIZATION_SHARED':'TOK_ORG_'+suffix,
 'PRIVATE_USER':'TOK_USER_'+suffix,
 'SYSTEM_SHARED':'TOK_SYSTEM_'+suffix,
}
ids={scope:create(scope,scope.lower(),tok) for scope,tok in scopes.items()}
# Create concurrency target visible to A and B by project
con_token='TOK_CONCURRENCY_'+suffix
con_id=create('PROJECT_SHARED','concurrency-target',con_token)
# Embed all new rows using system maintenance worker
worker=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'scripts/embedding_worker.py'),'--limit','500'],cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.
# Visibility matrix expected by spec
visible_expected={
 'A':set(scopes),
 'B':{'AGENT_TEAM','PROJECT_SHARED','ORGANIZATION_SHARED','SYSTEM_SHARED'},
 'C':{'SYSTEM_SHARED'},
}
actors={'A':A,'B':B,'C':C}
visibility={}; checks={}
for name,actor in actors.items():
    visibility[name]={}
    for scope,token in scopes.items():
        st,found=listed(actor,token); visible=ids[scope] in found
        visibility[name][scope]=visible
        checks[f'{name}_{scope}_VISIBILITY']=(st==200 and visible==(scope in visible_expected[name]))
# Semantic/context enforcement on a private memory
st_a,ctx_a,ctx_body_a=context_ids(A,scopes['AGENT_PRIVATE'])
st_b,ctx_b,ctx_body_b=context_ids(B,scopes['AGENT_PRIVATE'])
checks['A_PRIVATE_CONTEXT_VISIBLE']=st_a==200 and ids['AGENT_PRIVATE'] in ctx_a
checks['B_PRIVATE_CONTEXT_BLOCKED']=st_b==200 and ids['AGENT_PRIVATE'] not in ctx_b
# Direct DB RLS negative test for the same private row
raw=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip();h,p,d,u,pw=raw.split(':',4);dsn=f'host={h} port={p} dbname={d} user={u} password={pw} connect_timeout=5'
def db_visible(agent):
    with psycopg.connect(dsn) as conn:
        settings={'app.current_tenant':tenant,'app.current_agent':agent['X-Memory-Agent'],'app.current_user_id':agent['X-Memory-User'],'app.current_project':agent['X-Memory-Project'],'app.current_team':agent['X-Memory-Team'],'app.current_org':agent['X-Memory-Organization']}
        for k,v in settings.items(): conn.execute('select set_config(%s,%s,true)',(k,v))
        return conn.execute('select count(*) from memory_items where item_id=%s',(ids['AGENT_PRIVATE'],)).fetchone()[0]
checks['DB_RLS_A_SEES_PRIVATE']=db_visible(A)==1
checks['DB_RLS_B_CANNOT_SEE_PRIVATE']=db_visible(B)==0
# Concurrent optimistic revision: one must win, the other must explicitly conflict
def revise(actor,label):
    payload={'content':{'gate':'M5','winner_candidate':label},'content_text':f'Concurrent revision candidate {label} {suffix}','provenance':{'trusted':True,'proof':'M5_CONCURRENCY','worker':label},'confidence':1.0,'source':'sovereign-system','source_version':'M5','tags':['M5','CONCURRENCY',label],'changed_by':label,'expected_version':1}
    return label,*request('POST',f'/v1/memories/{con_id}/versions',{**actor,'Idempotency-Key':f'm5-con-{label}-{suffix}'},payload)
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
    results=list(ex.map(lambda args: revise(*args),[(A,'worker-a'),(B,'worker-b')]))
statuses=sorted(r[1] for r in results)
checks['CONCURRENCY_ONE_SUCCESS_ONE_409']=statuses==[201,409]
st_ver,ver_body=request('GET',f'/v1/memories/{con_id}/versions',A)
versions=ver_body.get('versions',[])
checks['CONCURRENCY_EXACTLY_TWO_VERSIONS']=st_ver==200 and len(versions)==2 and [int(v['version_no']) for v in versions]==[1,2]
# Leases and fencing
lease_key='m5-job-'+suffix
st_la,la=request('POST',f'/v1/leases/{lease_key}/acquire',A,{'ttl_seconds':60})
st_lb_block,lb_block=request('POST',f'/v1/leases/{lease_key}/acquire',B,{'ttl_seconds':60})
st_rel,rel=request('POST',f'/v1/leases/{lease_key}/release',A,{'fencing_token':int(la.get('fencing_token',0))}) if st_la==200 else (0,{})
st_lb,lb=request('POST',f'/v1/leases/{lease_key}/acquire',B,{'ttl_seconds':60})
st_stale,stale=request('POST',f'/v1/leases/{lease_key}/release',A,{'fencing_token':int(la.get('fencing_token',0))}) if st_la==200 else (0,{})
checks['LEASE_A_ACQUIRED']=st_la==200 and la.get('owner_agent_id')=='agent-a'
checks['LEASE_B_BLOCKED_WHILE_A_ACTIVE']=st_lb_block==409
checks['LEASE_A_RELEASED']=st_rel==200
checks['LEASE_B_ACQUIRED_AFTER_RELEASE']=st_lb==200 and lb.get('owner_agent_id')=='agent-b'
checks['FENCING_TOKEN_MONOTONIC']=st_lb==200 and int(lb.get('fencing_token',0))>int(la.get('fencing_token',0)) and int(lb.get('lease_version',0))>int(la.get('lease_version',0))
checks['STALE_FENCING_REJECTED']=st_stale==409
# Outbox, policies and audit chain
with psycopg.connect(dsn) as conn:
    conn.execute("select set_config('app.current_tenant','__SYSTEM__',true)")
    conn.execute("select set_config('app.current_agent','__SYSTEM__',true)")
    ev=conn.execute('select count(*) from memory_events where item_id=%s',(con_id,)).fetchone()[0]
    ob=conn.execute('select count(*) from memory_outbox o join memory_events e on e.event_id=o.event_id where e.item_id=%s',(con_id,)).fetchone()[0]
    policy=conn.execute("select count(*) from pg_policies where tablename='memory_items' and policyname='tenant_and_agent_isolation'").fetchone()[0]
    scopes_db={r[0] for r in conn.execute('select distinct sharing_scope from memory_items where tenant_id=%s',(tenant,)).fetchall()}
    lease_db=conn.execute('select owner_agent_id,lease_version,fencing_token from agent_leases where tenant_id=%s and lease_key=%s',(tenant,lease_key)).fetchone()
checks['OUTBOX_MATCHES_MEMORY_EVENTS']=ev>=2 and ob==ev
checks['AGENT_POLICY_INSTALLED']=policy==1
checks['ALL_SIX_SCOPES_PERSISTED']=set(scopes)<=scopes_db
checks['LEASE_DB_FINAL_OWNER_B']=lease_db is not None and lease_db[0]=='agent-b'
# Audit chain via system store
from memory_permanent.access_policy import AgentAccessContext  # noqa: E402
from memory_permanent.store import PostgresMemoryStore  # noqa: E402

chain=PostgresMemoryStore(dsn,tenant_id='__SYSTEM__',access=AgentAccessContext.system(),initialize=False).verify_audit_chain()
checks['AUDIT_CHAIN_OK']=bool(chain.get('ok'))
failed=[k for k,v in checks.items() if not v]
result={'generated_at':time.strftime('%Y-%m-%dT%H:%M:%S'),'gate':'M5','tenant':tenant,'namespace':ns,'item_ids':ids,'concurrency_item_id':con_id,'visibility':visibility,'concurrency_results':[{'worker':r[0],'status':r[1],'body':r[2]} for r in results],'lease':{'first':la,'blocked_status':st_lb_block,'second':lb,'stale_status':st_stale},'worker_exit':worker.returncode,'worker_stdout_tail':worker.stdout[-1000:],'outbox':{'events':ev,'outbox':ob},'audit':chain,'checks':checks,'failed_checks':failed,'GATE_M5':'PASS' if not failed else 'FAIL','MULTIAGENT_PROVEN':not failed}
(ROOT/'evidence/M5_GATE_PROOF.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
lines=['# Gate M5 - Multiagente','',f"**GATE_M5:** {result['GATE_M5']}",f"**MULTIAGENT_PROVEN:** {result['MULTIAGENT_PROVEN']}",'',f"Tenant: `{tenant}`",f"Concurrency item: `{con_id}`",'', '## Checks']+[f"- {k}: {'PASS' if v else 'FAIL'}" for k,v in checks.items()]
(ROOT/'evidence/M5_GATE_PROOF.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'GATE_M5':result['GATE_M5'],'failed':failed,'concurrency_statuses':statuses,'lease_tokens':[la.get('fencing_token'),lb.get('fencing_token')],'outbox':[ev,ob],'audit_ok':chain.get('ok')},indent=2,default=str))
raise SystemExit(0 if not failed else 1)
