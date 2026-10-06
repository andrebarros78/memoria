from __future__ import annotations

import json
import os
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg

ROOT=Path(r'C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0')
ADAPTER_ROOT=Path(r'C:\New Projet\MEMORIA-CLIENT-ADAPTER')
sys.path.insert(0,str(ADAPTER_ROOT/'src'))
from memoria_client_adapter import (  # noqa: E402
    MemoryClientAdapter,
    WindowsDpapiCredentialProvider,
)
from memoria_client_adapter import __version__ as adapter_version  # noqa: E402


def require(condition: object, detail: object = "proof assertion failed") -> None:
    if not condition:
        raise RuntimeError(f"proof requirement failed: {detail!r}")


BASE='http://127.0.0.1:8787'
AUTH_ROOT=Path(os.getenv('ProgramData',r'C:\ProgramData'))/'MemoriaPermanente'/'auth'/'clients'
client=MemoryClientAdapter(BASE,client_id='local-admin',credential_provider=WindowsDpapiCredentialProvider(AUTH_ROOT/'local-admin.dpapi'))


def raw_status(path:str,headers:dict[str,str]|None=None)->int:
    req=urllib.request.Request(BASE+path,method='GET',headers=headers or {})
    try:
        with urllib.request.urlopen(req,timeout=5) as r: return int(r.status)  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
    except urllib.error.HTTPError as exc:
        return int(exc.code)

suffix=uuid.uuid4().hex[:10]
namespace='P06_'+suffix.upper()
marker='MEMORIA_PLUS_P06_'+suffix
mission='mission-p06-'+suffix
session_id='sess-p06-'+suffix

health=client.health()
unsigned_old=raw_status('/v1/governor/contract')
govkey_old=raw_status('/v1/governor/contract',{'X-Governor-Key':'synthetic-not-authoritative'})
signed_old_status,signed_old_body=client.request('GET','/v1/governor/contract')

item_id=client.remember(
    namespace=namespace,memory_key='p06.source.'+suffix,category='FACT',
    content={'marker':marker,'value':'V1'},content_text=f'{marker} source version V1',
    provenance={'proof':'MEMORIA_PLUS_P06'},confidence=0.75,source='p06-proof',source_version='1',
    tags=['MEMORIA PLUS','P06','DERIVED_GRAPH'],sharing_scope='SYSTEM_SHARED',
    idempotency_key='p06-create-'+suffix,
)
status,versions=client.request('GET',f'/v1/memories/{item_id}/versions')
require(status == 200, 'prove_memoria_plus_p05_p06.py:55')
v1=versions['versions'][-1]
v1_version_id=str(v1['version_id']); v1_hash=str(v1['content_sha256'])

# Force embedding generation for the new item.
subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'scripts/embedding_worker.py'),'--limit','200'],cwd=str(ROOT),check=True,capture_output=True,text=True,timeout=120)  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.

ctx=client.retrieve_context(marker,namespaces=[namespace],limit=8)
require(item_id in {str(x.get('item_id')) for x in ctx.selected}, 'prove_memoria_plus_p05_p06.py:63')

cp=client.save_checkpoint(
    namespace=namespace,mission_id=mission,step_index=1,
    state={'objective':'prove derived invalidation','required_memory_ids':[item_id],'marker':marker},
)

session_payload={
    'session_id':session_id,'identity':{'proof':'P06','marker':marker},'scope':'MEMORIA_PLUS_P06',
    'objective':'prove context pack dependency invalidation','critical_rules':['preserve source version'],
    'operational_state':{'phase':'P06'},'last_confirmed_action':'SOURCE_V1_READY','blockers':[],
    'pending':['REVISE_TO_V2'],'next_safe_action':'PREPARE_ROTATION','active_authorizations':[],
    'required_memory_ids':[item_id],
}
s,body=client.request('POST','/v1/sessions',payload=session_payload); require(s == 201, (s, body))
s,body=client.request('POST',f'/v1/sessions/{session_id}/bindings',payload={'provider':'proof-provider-a','external_session_ref':'ext-p06-a-'+suffix}); require(s == 201, (s, body))
safe={'streaming_critical':False,'upload_unconfirmed':False,'non_idempotent_write_pending':False,'tool_call_unpersisted':False,'last_event_confirmed':True,'checkpoint_possible':True}
s,rot=client.request('POST','/v1/session-rotations/request',payload={'session_id':session_id,'safe_point':safe,'reason':'P06_DERIVED_GRAPH_PROOF'}); require(s == 201, (s, rot))
rotation_id=str(rot['rotation_id'])
s,prepared=client.request('POST',f'/v1/session-rotations/{rotation_id}/prepare',payload={'last_event_id':item_id}); require(s == 200, (s, prepared))
context_pack_id=str(prepared['context_pack']['context_pack_id'])
session_checkpoint_id=str(prepared['context_pack']['checkpoint_id'])

before=client.list_derived_artifacts(item_id=item_id,limit=100)
before_types={str(x['artifact_type']) for x in before if x['status']=='READY'}
expected_types={'EMBEDDING','RETRIEVAL_TRACE','CHECKPOINT','SESSION_CHECKPOINT','CONTEXT_PACK'}

revision_payload={
    'content':{'marker':marker,'value':'V2'},'content_text':f'{marker} source version V2',
    'provenance':{'proof':'MEMORIA_PLUS_P06_REVISION'},'confidence':0.75,'source':'p06-proof',
    'source_version':'2','tags':['MEMORIA PLUS','P06','DERIVED_GRAPH'],'expected_version':1,
}
s,rev=client.request('POST',f'/v1/memories/{item_id}/versions',payload=revision_payload,headers={'Idempotency-Key':'p06-revise-'+suffix}); require(s == 201, (s, rev))
v2_version_id=str(rev['version_id'])

# DB trigger must have staled every V1-bound artifact.
after=client.list_derived_artifacts(item_id=item_id,limit=100)
stale_v1=[x for x in after if x['status']=='STALE' and str(x.get('stale_source_version_id') or '')==v1_version_id]
stale_types={str(x['artifact_type']) for x in stale_v1}

# Generate V2 embedding; old V1 artifact must stay stale and a new V2 artifact must be READY.
subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'scripts/embedding_worker.py'),'--limit','200'],cwd=str(ROOT),check=True,capture_output=True,text=True,timeout=120)  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.
final_artifacts=client.list_derived_artifacts(item_id=item_id,limit=100)
ready_embeddings=[x for x in final_artifacts if x['artifact_type']=='EMBEDDING' and x['status']=='READY']

# Resolve dependency versions and state events directly without exposing credentials.
raw=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip(); h,p,d,u,pw=raw.split(':',4)
conn=psycopg.connect(f'host={h} port={p} dbname={d} user={u} password={pw}',row_factory=psycopg.rows.dict_row)
with conn.transaction():
    conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',true)")
    dep_rows=conn.execute("SELECT a.artifact_id,a.artifact_type,a.status,d.source_version_id,d.source_content_sha256 FROM memory_derived_artifacts a JOIN memory_artifact_dependencies d ON d.artifact_id=a.artifact_id WHERE d.source_item_id=%s ORDER BY a.artifact_type,a.created_at",(item_id,)).fetchall()
    events=conn.execute("SELECT artifact_id,old_status,new_status,reason,source_version_id FROM memory_artifact_state_events WHERE source_version_id=%s ORDER BY seq",(v1_version_id,)).fetchall()
    trigger=conn.execute("SELECT count(*) AS n FROM pg_trigger WHERE tgname='trg_invalidate_derived_on_new_version' AND NOT tgisinternal").fetchone()['n']
    schema=conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()['value']
    legacy_active=int(conn.execute("SELECT count(*) AS n FROM governor_project_bindings WHERE status='ACTIVE'").fetchone()['n'])
conn.close()
ready_v2_dep=False
for emb in ready_embeddings:
    deps=[r for r in dep_rows if str(r['artifact_id'])==str(emb['artifact_id'])]
    if any(str(r['source_version_id'])==v2_version_id for r in deps): ready_v2_dep=True

active_refs=[]
for path in (ROOT/'src/memory_permanent').glob('*.py'):
    text=path.read_text(encoding='utf-8-sig')
    if 'X-Governor-Key' in text or '/v1/governor' in text:
        active_refs.append(path.name)

checks={
    'api_0_14_2':health.get('version')=='0.14.2',
    'universal_adapter_1_1':adapter_version=='1.1.0',
    'legacy_unsigned_401':unsigned_old==401,
    'legacy_governor_key_not_auth_401':govkey_old==401,
    'legacy_signed_route_removed_404':signed_old_status==404,
    'no_active_governor_auth_source':active_refs==[],
    'all_required_artifact_types_ready_before_revision':expected_types.issubset(before_types),
    'all_required_artifact_types_stale_after_revision':expected_types.issubset(stale_types),
    'stale_bound_to_v1':len(stale_v1)>=len(expected_types),
    'state_transition_events_recorded':len(events)>=len(expected_types) and all(str(x['new_status'])=='STALE' for x in events),
    'db_invalidation_trigger_active':int(trigger)==1,
    'v2_embedding_ready':bool(ready_embeddings),
    'v2_embedding_depends_on_v2':ready_v2_dep,
    'schema_0_14_2':schema=='memory-0.14.2',
    'generic_checkpoint_via_universal_adapter':bool(cp.get('checkpoint_id')),
    'context_pack_created':bool(context_pack_id and session_checkpoint_id),
    'legacy_bindings_disabled':legacy_active==0,
}
failed=[k for k,v in checks.items() if not v]
proof={
    'generated_at':datetime.now(UTC).isoformat(),'tag':'MEMORIA PLUS','block':['05','06'],
    'result':'PASS' if not failed else 'FAIL','failed':failed,'checks':checks,
    'p05':{'adapter_version':adapter_version,'unsigned_old':unsigned_old,'govkey_old':govkey_old,'signed_old':signed_old_status,'active_legacy_refs':active_refs,'active_legacy_bindings':legacy_active},
    'p06':{'item_id':item_id,'v1_version_id':v1_version_id,'v1_content_sha256':v1_hash,'v2_version_id':v2_version_id,'before_ready_types':sorted(before_types),'stale_v1_types':sorted(stale_types),'stale_v1_count':len(stale_v1),'state_events':len(events),'dependency_rows':len(dep_rows),'context_pack_id':context_pack_id,'session_checkpoint_id':session_checkpoint_id,'checkpoint_id':cp.get('checkpoint_id'),'ready_v2_embeddings':len(ready_embeddings)},
    'schema':schema,
}
EV=ROOT/'evidence'; EV.mkdir(exist_ok=True)
(EV/'MEMORIA_PLUS_P05_P06_PROOF.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
lines=['# MEMORIA PLUS P05/P06 PROOF','',f"**Result:** {proof['result']}",'',f"- Universal Adapter: {adapter_version}",f"- Legacy unsigned: HTTP {unsigned_old}",f"- Legacy X-Governor-Key only: HTTP {govkey_old}",f"- Legacy route with valid universal auth: HTTP {signed_old_status}",f"- V1 stale artifact types: {', '.join(sorted(stale_types))}",f"- V2 ready embeddings: {len(ready_embeddings)}",f"- Schema: {schema}",'','## Checks']+[f"- {k}: {'PASS' if v else 'FAIL'}" for k,v in checks.items()]
(EV/'MEMORIA_PLUS_P05_P06_PROOF.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'result':proof['result'],'failed':failed,'p05':proof['p05'],'p06':proof['p06'],'schema':schema},ensure_ascii=False,indent=2))
raise SystemExit(0 if not failed else 1)
