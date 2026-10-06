from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT=Path(r'C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0')
sys.path.insert(0,str(ROOT/'src'))
from memory_permanent.access_policy import AgentAccessContext  # noqa: E402
from memory_permanent.canonical_mutation import (  # noqa: E402
    CanonicalMutationRequired,
    CanonicalMutationService,
)
from memory_permanent.conversation_ingestion import (  # noqa: E402
    ConversationIngestionRepository,
)
from memory_permanent.session_rotation import SessionRotationRepository  # noqa: E402
from memory_permanent.signed_client import SignedMemoryClient  # noqa: E402
from memory_permanent.store import PostgresMemoryStore  # noqa: E402

suffix=uuid.uuid4().hex[:12].upper()
client=SignedMemoryClient('http://127.0.0.1:8787','local-admin')
headers={'X-Memory-Tenant':'LEGACY'}
secrets={name:f'P02-{name}-{uuid.uuid4().hex}{uuid.uuid4().hex}' for name in [
 'memory','provenance','validation','revision','application','expected','actual','outcome_evidence',
 'checkpoint','query','session_identity','session_objective','session_state','rotation','ingestion_text','ingestion_objective','embedding_error'
]}

def req(method,path,payload=None,extra=None,expected=None):
    h=dict(headers); h.update(extra or {})
    status,body=client.request(method,path,payload,extra_headers=h,timeout=60)
    if expected is not None and status!=expected:
        raise RuntimeError({'method':method,'path':path,'status':status,'body':body})
    return status,body

create={
 'namespace':'P02_PROOF','memory_key':'p02-'+suffix,'category':'FACT',
 'content':{'password':secrets['memory'],'nested':{'client_secret':secrets['provenance']}},
 'content_text':f"proof password={secrets['memory']}",
 'provenance':{'api_key':secrets['provenance'],'trusted':True},
 'confidence':0.70,'source':'sovereign-system','tags':['MEMORIA PLUS','P01','P02'],
 'sharing_scope':'SYSTEM_SHARED','validation_status':'UNVALIDATED','governor_eligible':False,
}
_,created=req('POST','/v1/memories',create,{'Idempotency-Key':'p02-create-'+suffix},201)
item_id=created['item_id']
_,versions=req('GET',f'/v1/memories/{item_id}/versions',expected=200)
v1=versions['versions'][-1]

_,val=req('POST',f'/v1/memories/{item_id}/validation',{
 'expected_version':1,'expected_content_sha256':v1['content_sha256'],'status':'VALIDATED','governor_eligible':False,
 'evidence':{'password':secrets['validation'],'note':f"api_key={secrets['validation']}"},
},expected=200)

_,rev=req('POST',f'/v1/memories/{item_id}/versions',{
 'content':{'api_key':secrets['revision'],'state':'B'},'content_text':f"revision api_key={secrets['revision']}",
 'provenance':{'password':secrets['revision'],'trusted':True},'confidence':0.71,'source':'sovereign-system',
 'tags':['MEMORIA PLUS','P02','REVISION'],'expected_version':1,
},{'Idempotency-Key':'p02-revise-'+suffix},201)
if rev.get('validation_status')!='UNVALIDATED' or rev.get('governor_eligible') is not False:
    raise RuntimeError('revision did not invalidate trust')
_,versions2=req('GET',f'/v1/memories/{item_id}/versions',expected=200)
v2=versions2['versions'][-1]

_,app=req('POST',f'/v1/experience/applications?item_id={item_id}',{
 'action_ref':'action:p02:'+suffix,'mission_id':'mission:p02:'+suffix,'decision_id':'decision:p02:'+suffix,
 'context':{'password':secrets['application']},'occurred_at':datetime.now(UTC).isoformat(),
},expected=201)
_,out=req('POST',f"/v1/experience/applications/{app['application_id']}/outcome",{
 'success':True,'outcome_type':'P02_PROOF','expected':{'api_key':secrets['expected']},
 'actual':{'password':secrets['actual']},'confidence_delta':0.0,
 'evidence':{'client_secret':secrets['outcome_evidence']},'occurred_at':datetime.now(UTC).isoformat(),
},expected=201)

_,cp=req('POST','/v1/checkpoints',{
 'namespace':'P02_PROOF','mission_id':'mission:p02:'+suffix,'step_index':1,
 'state':{'password':secrets['checkpoint'],'nested':{'api_key':secrets['checkpoint']}},
 'checkpoint_id':'cp-p02-'+suffix,
},expected=201)

_,ctx=req('POST','/v1/context/retrieve',{
 'query':f"password={secrets['query']}",'namespaces':['P02_PROOF'],'limit':3,
},expected=200)
trace_id=ctx['trace_id']

session_id='sess-p02-'+suffix
_,sess=req('POST','/v1/sessions',{
 'session_id':session_id,'identity':{'password':secrets['session_identity']},'scope':'P02_PROOF',
 'objective':f"objective api_key={secrets['session_objective']}",
 'critical_rules':[{'client_secret':secrets['session_state']}],
 'operational_state':{'password':secrets['session_state']},'last_confirmed_action':None,
 'blockers':[{'api_key':secrets['session_state']}],'pending':[],'next_safe_action':'CONTINUE',
 'active_authorizations':[{'password':secrets['session_state']}],'required_memory_ids':[item_id],
},expected=201)
_,binding=req('POST',f'/v1/sessions/{session_id}/bindings',{
 'provider':'proof-provider','external_session_ref':'proof-session-'+suffix,
},expected=201)

safe={
 'streaming_critical':False,'upload_unconfirmed':False,'non_idempotent_write_pending':False,
 'tool_call_unpersisted':False,'last_event_confirmed':True,'checkpoint_possible':True,
 'password':secrets['rotation'],
}
_,rotation=req('POST','/v1/session-rotations/request',{
 'session_id':session_id,'safe_point':safe,'memory_before_mb':10.0,
 'reason':f"rotation password={secrets['rotation']}",
},expected=201)
rotation_id=rotation['rotation_id']

message_id='msg-p02-'+suffix
_,ing=req('POST','/v1/conversation-ingestion/turn',{
 'provider':'proof-provider','external_session_ref':'proof-conv-'+suffix,
 'objective':f"objective api_key={secrets['ingestion_objective']}",'role':'user',
 'text':f"conversation password={secrets['ingestion_text']}",'message_id':message_id,'ordinal':0,
 'capture_source':'P02_PROOF','process_now':True,
},expected=201)
ing_event_id=ing.get('event_id')

parts=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip().split(':',4)
h,p,d,u,pw=parts
dsn=f'host={h} port={p} dbname={d} user={u} password={pw} connect_timeout=5'
store=PostgresMemoryStore(dsn,tenant_id='LEGACY',access=AgentAccessContext.system())
CanonicalMutationService(store,actor_id='p02-proof').mark_embedding_failed(
 item_id,model_id='p02-proof-model',content_sha256=v2['content_sha256'],
 error_type='P02ProofError',error_message=f"password={secrets['embedding_error']}",
)

bypass_store=bypass_session=bypass_ingestion=False
try:
    store.classify([], 'ATIVA', changed_by='direct-bypass')
except CanonicalMutationRequired:
    bypass_store=True
try:
    SessionRotationRepository(store,initialize=False).create_session(
        session_id='bypass-'+suffix,identity={},scope='X',objective='X',critical_rules=[],operational_state={},
        last_confirmed_action=None,blockers=[],pending=[],next_safe_action=None,active_authorizations=[],required_memory_ids=[]
    )
except CanonicalMutationRequired:
    bypass_session=True
try:
    ConversationIngestionRepository(store).enqueue_turn(
        provider='x',external_session_ref='x',objective='x',role='user',text='x',message_id='x-'+suffix,ordinal=0,process_now=False
    )
except CanonicalMutationRequired:
    bypass_ingestion=True

with psycopg.connect(dsn,row_factory=dict_row) as conn:
    conn.execute("select set_config('app.current_tenant','__SYSTEM__',true)")
    def rows_text(sql,args=()):
        rows=conn.execute(sql,args).fetchall()
        return '\n'.join(json.dumps(dict(r),default=str,sort_keys=True) for r in rows)
    persisted={
      'memory_items':rows_text('select * from memory_items where item_id=%s',(item_id,)),
      'memory_versions':rows_text('select * from memory_versions where item_id=%s',(item_id,)),
      'memory_events':rows_text('select * from memory_events where item_id=%s',(item_id,)),
      'memory_validations':rows_text('select * from memory_validations where item_id=%s',(item_id,)),
      'memory_applications':rows_text('select * from memory_applications where application_id=%s',(app['application_id'],)),
      'memory_outcomes':rows_text('select * from memory_outcomes where application_id=%s',(app['application_id'],)),
      'experience_edges':rows_text('select * from memory_experience_edges where from_id in (%s,%s) or to_id in (%s,%s)',(app['application_id'],item_id,app['application_id'],item_id)),
      'retrieval_traces':rows_text('select * from retrieval_traces where trace_id=%s',(trace_id,)),
      'checkpoints':rows_text('select * from checkpoints where checkpoint_id=%s',(cp['checkpoint_id'],)),
      'sovereign_sessions':rows_text('select * from sovereign_sessions where session_id=%s or session_id=%s',(session_id,ing.get('session_id'))),
      'external_bindings':rows_text('select * from external_session_bindings where session_id=%s or session_id=%s',(session_id,ing.get('session_id'))),
      'session_rotations':rows_text('select * from session_rotations where rotation_id=%s',(rotation_id,)),
      'conversation_ingestion':rows_text('select * from conversation_ingestion_events where message_id=%s',(message_id,)),
      'session_checkpoints':rows_text('select * from session_checkpoints where session_id=%s',(ing.get('session_id'),)),
      'context_packs':rows_text('select * from context_packs where session_id=%s',(ing.get('session_id'),)),
      'memory_embeddings':rows_text('select item_id,model_id,status,error_type,error_message,content_sha256 from memory_embeddings where item_id=%s',(item_id,)),
      'audit_events':rows_text('select event_type,target_id,payload from audit_events where target_id=any(%s)',([item_id,session_id,rotation_id,app['application_id'],ing_event_id or ''],)),
    }

raw_hits={table:sum(1 for secret in secrets.values() if secret in text) for table,text in persisted.items()}
all_text='\n'.join(persisted.values())
refs=all_text.count('vault://memory/legacy/')
health=req('GET','/health',expected=200)[1]
checks={
 'API_VERSION_0_12_0':health.get('version')=='0.12.0',
 'DIRECT_STORE_BYPASS_BLOCKED':bypass_store,
 'DIRECT_SESSION_REPO_BYPASS_BLOCKED':bypass_session,
 'DIRECT_INGESTION_REPO_BYPASS_BLOCKED':bypass_ingestion,
 'NO_SYNTHETIC_SECRET_PLAINTEXT_IN_PROOF_ROWS':all(v==0 for v in raw_hits.values()),
 'VAULT_REFS_PRESENT_ACROSS_PERSISTED_PAYLOADS':refs>=10,
 'REVISION_INVALIDATED_PRIOR_TRUST':rev.get('validation_status')=='UNVALIDATED' and rev.get('governor_eligible') is False,
 'SESSION_ROTATION_CREATED':bool(rotation_id),
 'CONVERSATION_INGESTION_PROCESSED':str(ing.get('status','')).upper()=='PROCESSED',
 'RETRIEVAL_TRACE_CREATED':bool(trace_id),
 'CHECKPOINT_CREATED':bool(cp.get('checkpoint_id')),
 'OUTCOME_CREATED':bool(out.get('outcome_id')),
}
failed=[k for k,v in checks.items() if not v]
proof={
 'generated_at':datetime.now(UTC).isoformat(),'api_version':'0.12.0','tag':'MEMORIA PLUS',
 'priorities':['01_CANONICAL_MUTATION_SERVICE','02_SANITIZE_ALL_PERSISTENT_PAYLOADS'],
 'item_id':item_id,'session_id':session_id,'rotation_id':rotation_id,'trace_id':trace_id,
 'raw_secret_hits_by_table':raw_hits,'vault_ref_occurrences':refs,'checks':checks,'failed_checks':failed,
 'P01_CANONICAL_MUTATION_SERVICE':'PASS' if not failed else 'FAIL',
 'P02_PERSISTENT_PAYLOAD_SANITIZATION':'PASS' if not failed else 'FAIL',
}
(ROOT/'evidence/MEMORIA_PLUS_P01_P02_PROOF.json').write_text(json.dumps(proof,indent=2,default=str),encoding='utf-8')
(ROOT/'evidence/MEMORIA_PLUS_P01_P02_PROOF.md').write_text(
 '# MEMORIA PLUS - P01/P02 Proof\n\n'+f"Result: {'PASS' if not failed else 'FAIL'}\n\n"+
 '\n'.join(f"- {k}: {'PASS' if v else 'FAIL'}" for k,v in checks.items())+'\n',encoding='utf-8')
print(json.dumps({'result':'PASS' if not failed else 'FAIL','failed':failed,'raw_hits':raw_hits,'vault_refs':refs,'item_id':item_id,'session_id':session_id,'rotation_id':rotation_id},indent=2))
raise SystemExit(0 if not failed else 1)
