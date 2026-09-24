from __future__ import annotations

import json
import os
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from memory_permanent.signed_client import SignedMemoryClient

ROOT=Path(r'C:\New Projet\MEMORIA-PERMANENTE')

writer=SignedMemoryClient('http://127.0.0.1:8787','governor-runtime')
admin=SignedMemoryClient('http://127.0.0.1:8787','local-admin')
suffix=uuid.uuid4().hex[:12].upper()
project='TRUST-PROOF-'+suffix
common={'X-Memory-Tenant':'LEGACY','X-Memory-Project':project}
secret1='rev-proof-initial-'+uuid.uuid4().hex+uuid.uuid4().hex
secret2='rev-proof-revision-'+uuid.uuid4().hex+uuid.uuid4().hex

base={
 'namespace':'TRUST_HARDENING', 'memory_key':'revision-trust-'+suffix, 'category':'FACT',
 'content':{'state':'A','password':secret1}, 'content_text':f'Initial state A password={secret1}',
 'provenance':{'trusted':True,'trust':{'trusted':True},'claimed_by':'caller'},
 'confidence':0.8,'source':'sovereign-system','source_version':'proof','tags':['TRUST','REVISION'],
 'changed_by':'caller-asserted','sharing_scope':'PROJECT_SHARED','project_id':project,
 'validation_status':'UNVALIDATED','governor_eligible':False,
}
st_create,created=writer.request('POST','/v1/memories',base,extra_headers={**common,'Idempotency-Key':'trust-create-'+suffix})
if st_create!=201: raise RuntimeError((st_create,created))
item_id=created['item_id']

# writer cannot mint validation on create nor use validation endpoint
bad=dict(base); bad['memory_key']='bad-validation-'+suffix; bad['validation_status']='VALIDATED'; bad['governor_eligible']=True
st_bad_create,_=writer.request('POST','/v1/memories',bad,extra_headers={**common,'Idempotency-Key':'trust-bad-'+suffix})

# vectorize so revision must explicitly stale the derived embedding
worker=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'scripts/embedding_worker.py'),'--limit','500'],cwd=str(ROOT),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.

st_versions,vbody=admin.request('GET',f'/v1/memories/{item_id}/versions',extra_headers=common)
v1=vbody['versions'][-1]
st_writer_validate,_=writer.request('POST',f'/v1/memories/{item_id}/validation',{
 'expected_version':1,'expected_content_sha256':v1['content_sha256'],'status':'VALIDATED','governor_eligible':True,'evidence':{'proof':'writer-must-not-validate'}
},extra_headers=common)
st_admin_validate,validated=admin.request('POST',f'/v1/memories/{item_id}/validation',{
 'expected_version':1,'expected_content_sha256':v1['content_sha256'],'status':'VALIDATED','governor_eligible':True,'evidence':{'proof':'authority-validation'}
},extra_headers=common)

revision={
 'content':{'state':'B','api_key':secret2}, 'content_text':f'Revised state B api_key={secret2}',
 'provenance':{'trusted':True,'trust':{'trusted':True},'trust_assigned_by':'caller','claimed':'sovereign'},
 'confidence':0.82,'source':'sovereign-system','source_version':'proof-v2','tags':['TRUST','REVISION','V2'],
 'changed_by':'caller-asserted','expected_version':1,
}
st_revision,revised=writer.request('POST',f'/v1/memories/{item_id}/versions',revision,extra_headers={**common,'Idempotency-Key':'trust-revise-'+suffix})
if st_revision!=201: raise RuntimeError((st_revision,revised))

os.environ.setdefault('PGPASSFILE',str(ROOT/'runtime/secrets/pgpass.conf'))
dsn='postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary'
with psycopg.connect(dsn) as conn:
 conn.execute("select set_config('app.current_tenant','LEGACY',true)")
 row=conn.execute("select content_json,content_text,provenance,source,validation_status,governor_eligible,content_sha256,application_count,success_count,failure_count from memory_items where item_id=%s",(item_id,)).fetchone()
 emb=conn.execute("select status,content_sha256 from memory_embeddings where item_id=%s",(item_id,)).fetchone()
 versions=conn.execute("select version_no,content_json,content_text,provenance,source,content_sha256 from memory_versions where item_id=%s order by version_no",(item_id,)).fetchall()
 validations=conn.execute("select version_no,content_sha256,status,governor_eligible,validator_client_id from memory_validations where item_id=%s order by created_at",(item_id,)).fetchall()
 audits=[str(r[0]) for r in conn.execute("select payload::text from audit_events where target_id=%s order by seq",(item_id,)).fetchall()]

blob='\n'.join([str(row[0]),str(row[1]),json.dumps(row[2]),str(row[3])]+[str(x) for v in versions for x in v]+audits)
prov=dict(row[2] or {})
refs=list(prov.get('secret_refs') or [])

# Revalidate V2 via privileged authority, then exercise outcome learning.
st_versions2,vbody2=admin.request('GET',f'/v1/memories/{item_id}/versions',extra_headers=common)
v2=vbody2['versions'][-1]
st_revalidate,revalidated=admin.request('POST',f'/v1/memories/{item_id}/validation',{
 'expected_version':2,'expected_content_sha256':v2['content_sha256'],'status':'VALIDATED','governor_eligible':True,'evidence':{'proof':'v2-revalidation'}
},extra_headers=common)
occurred=(datetime.now(UTC)-timedelta(minutes=5)).isoformat()
st_app,application=admin.request('POST',f'/v1/experience/applications?item_id={item_id}',{
 'action_ref':'action:trust-proof','mission_id':'mission:'+suffix,'decision_id':'decision:'+suffix,
 'context':{'expected':'state B should improve result'},'occurred_at':occurred,
},extra_headers=common)
if st_app!=201: raise RuntimeError((st_app,application))
st_out,outcome=admin.request('POST',f"/v1/experience/applications/{application['application_id']}/outcome",{
 'success':True,'outcome_type':'PROOF_SUCCESS','expected':{'value':'improve'},'actual':{'value':'improved'},
 'confidence_delta':0.05,'evidence':{'proof':'closed-loop'},'occurred_at':datetime.now(UTC).isoformat(),
},extra_headers=common)
if st_out!=201: raise RuntimeError((st_out,outcome))
st_graph,graph=admin.request('GET',f"/v1/experience/graph?node_type=MEMORY&node_id={item_id}",extra_headers=common)

with psycopg.connect(dsn) as conn:
 conn.execute("select set_config('app.current_tenant','LEGACY',true)")
 final=conn.execute("select validation_status,governor_eligible,application_count,success_count,failure_count,confidence from memory_items where item_id=%s",(item_id,)).fetchone()
 appdb=conn.execute("select occurred_at,observed_at,version_id,content_sha256 from memory_applications where application_id=%s",(application['application_id'],)).fetchone()
 outdb=conn.execute("select occurred_at,observed_at,success,confidence_delta from memory_outcomes where application_id=%s",(application['application_id'],)).fetchone()
 audit_chain_count=conn.execute("select count(*) from audit_events where target_id=%s and event_type='MEMORY_VALIDATION_INVALIDATED'",(item_id,)).fetchone()[0]

checks={
 'CREATE_OK':st_create==201,
 'GENERAL_WRITER_CANNOT_CREATE_VALIDATED':st_bad_create==403,
 'GENERAL_WRITER_CANNOT_VALIDATE':st_writer_validate==403,
 'AUTHORITY_VALIDATED_V1':st_admin_validate==200 and validated.get('validation_status')=='VALIDATED' and validated.get('governor_eligible') is True,
 'REVISION_OK':st_revision==201 and revised.get('validation_status')=='UNVALIDATED' and revised.get('governor_eligible') is False,
 'REVISION_SECRET_NOT_PLAINTEXT':secret2 not in blob,
 'INITIAL_SECRET_NOT_PLAINTEXT':secret1 not in blob,
 'REVISION_SECRET_REF_PRESENT':bool(refs),
 'CALLER_TRUST_IGNORED':prov.get('trusted') is False and prov.get('trust_assigned_by')=='memory-api-identity',
 'SOURCE_DERIVED_FROM_AUTH_IDENTITY':row[3]=='authenticated-client:governor-runtime' and prov.get('asserted_source')=='sovereign-system',
 'VALIDATION_INVALIDATED_ON_CONTENT_CHANGE':row[4]=='UNVALIDATED' and row[5] is False and audit_chain_count>=1,
 'EMBEDDING_STALE_ON_CONTENT_CHANGE':emb is not None and emb[0]=='STALE',
 'V1_VALIDATION_PRESERVED_AS_HISTORY':len(validations)>=1 and validations[0][0]==1 and validations[0][2]=='VALIDATED',
 'V2_REVALIDATION_REQUIRED_AND_DONE':st_revalidate==200 and revalidated.get('version_no')==2,
 'APPLICATION_RECORDED':st_app==201 and outcome.get('application_count')==1,
 'OUTCOME_COUNTERS_UPDATED':st_out==201 and int(final[2])==1 and int(final[3])==1 and int(final[4])==0,
 'CONFIDENCE_ADJUSTED':abs(float(final[5])-0.87)<1e-9,
 'EXPERIENCE_GRAPH_CREATED':st_graph==200 and len(graph.get('edges') or [])>=2,
 'BITEMPORAL_APPLICATION':appdb is not None and appdb[0] < appdb[1],
 'OUTCOME_RECORDED':outdb is not None and bool(outdb[2]) is True,
 'WORKER_READY_BEFORE_REVISION':worker.returncode==0,
}
failed=[k for k,v in checks.items() if not v]
result={
 'generated_at':datetime.now(UTC).isoformat(),'item_id':item_id,'project':project,
 'statuses':{'bad_create':st_bad_create,'writer_validate':st_writer_validate,'admin_validate':st_admin_validate,'revision':st_revision,'revalidate':st_revalidate,'application':st_app,'outcome':st_out},
 'validation_history':[{'version_no':x[0],'content_sha256':x[1],'status':x[2],'governor_eligible':x[3],'validator_client_id':x[4]} for x in validations], 'provenance_after_revision':prov,
 'application_id':application.get('application_id'),'outcome_id':outcome.get('outcome_id'),'graph_edges':len(graph.get('edges') or []),
 'checks':checks,'failed_checks':failed,'TRUST_OUTCOME_HARDENING':'PASS' if not failed else 'FAIL'
}
(ROOT/'evidence/TRUST_OUTCOME_HARDENING_PROOF.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
print(json.dumps({'result':result['TRUST_OUTCOME_HARDENING'],'item_id':item_id,'failed':failed,'statuses':result['statuses'],'graph_edges':result['graph_edges']},indent=2))
raise SystemExit(0 if not failed else 1)
