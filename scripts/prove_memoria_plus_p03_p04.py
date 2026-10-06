from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg

ROOT=Path(r'C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0')
sys.path.insert(0,str(ROOT/'src'))
from memory_permanent.signed_client import SignedMemoryClient  # noqa: E402

client=SignedMemoryClient('http://127.0.0.1:8787','local-admin')
suffix=uuid.uuid4().hex[:12].upper()
project='MEMORIA-PLUS-P03P04-'+suffix
headers={'X-Memory-Tenant':'LEGACY','X-Memory-Project':project}

create={
    'namespace':'MEMORIA_PLUS_PROOF','memory_key':'p03p04-'+suffix,'category':'FACT',
    'content':{'state':'V1','claim':'version-bound learning proof'},
    'content_text':'V1 baseline for version-bound learning proof',
    'provenance':{'proof':'MEMORIA PLUS 03/04'},'confidence':0.60,'source':'proof-client',
    'source_version':'p03p04','tags':['MEMORIA PLUS','P03','P04'],
    'sharing_scope':'PROJECT_SHARED','project_id':project,
    'validation_status':'UNVALIDATED','governor_eligible':False,
}
st,body=client.request('POST','/v1/memories',create,extra_headers={**headers,'Idempotency-Key':'p03p04-create-'+suffix})
if st!=201: raise RuntimeError(('create',st,body))
item_id=body['item_id']

st,v=client.request('GET',f'/v1/memories/{item_id}/versions',extra_headers=headers)
if st!=200: raise RuntimeError(('versions1',st,v))
v1=v['versions'][-1]

# Apply V1 before the memory changes.
app1_payload={
    'action_ref':'action:p03:v1','mission_id':'mission:'+suffix,'decision_id':'decision:v1:'+suffix,
    'context':{'expected':'V1 application tracked by exact version'},'occurred_at':datetime.now(UTC).isoformat(),
}
st,app1=client.request('POST',f'/v1/experience/applications?item_id={item_id}',app1_payload,extra_headers=headers)
if st!=201: raise RuntimeError(('app1',st,app1))

# Revise to V2 before the V1 outcome arrives.
rev={
    'content':{'state':'V2','claim':'current version must not inherit V1 learning'},
    'content_text':'V2 current version; V1 outcome must not change this confidence',
    'provenance':{'proof':'MEMORIA PLUS 03/04 revision'},'confidence':0.70,'source':'proof-client',
    'source_version':'p03p04-v2','tags':['MEMORIA PLUS','P03','P04','V2'],'expected_version':1,
}
st,revbody=client.request('POST',f'/v1/memories/{item_id}/versions',rev,extra_headers={**headers,'Idempotency-Key':'p03p04-revise-'+suffix})
if st!=201: raise RuntimeError(('revise',st,revbody))

parts=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip().split(':',4)
h,p,d,u,pw=parts
dsn=f'host={h} port={p} dbname={d} user={u} password={pw} connect_timeout=5'

def db_snapshot():
    with psycopg.connect(dsn) as conn:
        conn.execute("select set_config('app.current_tenant','__SYSTEM__',true)")
        item=conn.execute("select confidence,application_count,success_count,failure_count from memory_items where item_id=%s",(item_id,)).fetchone()
        versions=conn.execute("select version_id,version_no,confidence,content_sha256 from memory_versions where item_id=%s order by version_no",(item_id,)).fetchall()
        learning=conn.execute("select version_id,version_no,base_confidence,learned_confidence,application_count,success_count,failure_count,current_policy_version from memory_version_learning where item_id=%s order by version_no",(item_id,)).fetchall()
        events=conn.execute("select learning_event_id,application_id,version_id,version_no,policy_version,success,authority_tier,components,computed_delta,confidence_before,confidence_after,applied_to_current_item from memory_learning_events where item_id=%s order by observed_at",(item_id,)).fetchall()
        outcomes=conn.execute("select outcome_id,application_id,confidence_delta,policy_version,computed_confidence_delta,learning_event_id from memory_outcomes where item_id=%s order by observed_at",(item_id,)).fetchall()
        schema=conn.execute("select value from schema_meta where key='schema_version'").fetchone()[0]
        return item,versions,learning,events,outcomes,schema

before_old=db_snapshot()
confidence_v2_before_old=float(before_old[0][0])

# Caller asks for a huge NEGATIVE delta even though success=True. It must be ignored.
out1_payload={
    'success':True,'outcome_type':'V1_SUCCESS_AFTER_V2_EXISTS',
    'expected':{'result':'success'},'actual':{'result':'success','sample_size':25},
    'confidence_delta':-0.99,
    'evidence':{'proof_ref':'proof:v1:'+suffix,'independent_refs':['e1','e2']},
    'occurred_at':datetime.now(UTC).isoformat(),
}
st,out1=client.request('POST',f"/v1/experience/applications/{app1['application_id']}/outcome",out1_payload,extra_headers=headers)
if st!=201: raise RuntimeError(('out1',st,out1))
after_old=db_snapshot()
confidence_v2_after_old=float(after_old[0][0])

# Duplicate outcome must remain impossible.
st_dup,dup=client.request('POST',f"/v1/experience/applications/{app1['application_id']}/outcome",out1_payload,extra_headers=headers)

# Apply V2 and record a failure while caller asks for huge POSITIVE delta. Policy must compute negative.
app2_payload={
    'action_ref':'action:p04:v2','mission_id':'mission:'+suffix,'decision_id':'decision:v2:'+suffix,
    'context':{'expected':'V2 failure lowers only V2 learned confidence'},'occurred_at':datetime.now(UTC).isoformat(),
}
st,app2=client.request('POST',f'/v1/experience/applications?item_id={item_id}',app2_payload,extra_headers=headers)
if st!=201: raise RuntimeError(('app2',st,app2))
out2_payload={
    'success':False,'outcome_type':'V2_FAILURE',
    'expected':{'result':'success'},'actual':{'result':'failed','sample_size':25},
    'confidence_delta':0.99,
    'evidence':{'proof_ref':'proof:v2:'+suffix,'independent_refs':['e3']},
    'occurred_at':datetime.now(UTC).isoformat(),
}
st,out2=client.request('POST',f"/v1/experience/applications/{app2['application_id']}/outcome",out2_payload,extra_headers=headers)
if st!=201: raise RuntimeError(('out2',st,out2))
final=db_snapshot()

st_learning,learning_api=client.request('GET',f'/v1/memories/{item_id}/learning',extra_headers=headers)

# Append-only proof: mutation of learning event and policy version must be rejected.
with psycopg.connect(dsn) as conn:
    conn.execute("select set_config('app.current_tenant','__SYSTEM__',true)")
    learning_update_blocked=False
    policy_update_blocked=False
    try:
        conn.execute("update memory_learning_events set computed_delta=0 where learning_event_id=%s",(out1['learning_event_id'],))
        conn.commit()
    except psycopg.Error:
        conn.rollback(); learning_update_blocked=True
    try:
        conn.execute("update learning_policy_versions set algorithm='tampered' where policy_version='LP-1.0.0'")
        conn.commit()
    except psycopg.Error:
        conn.rollback(); policy_update_blocked=True

item,versions,learning,events,outcomes,schema=final
v1id=str(versions[0][0]); v2id=str(versions[1][0])
learn_by_ver={int(x[1]):x for x in learning}
event_by_app={str(x[1]):x for x in events}
outcome_by_app={str(x[1]):x for x in outcomes}

checks={
    'SCHEMA_013':schema=='memory-0.13.0',
    'TWO_VERSIONS':len(versions)==2 and v1id==app1['version_id'] and v2id==app2['version_id'],
    'V1_OUTCOME_CALLER_DELTA_IGNORED':out1.get('caller_confidence_delta_ignored') is True and float(out1['computed_confidence_delta'])>0 and abs(float(out1['computed_confidence_delta'])+0.99)>0.5,
    'V1_OUTCOME_NOT_APPLIED_TO_V2':out1.get('applied_to_current_item') is False and abs(confidence_v2_after_old-confidence_v2_before_old)<1e-12 and abs(confidence_v2_after_old-0.70)<1e-12,
    'V1_PROJECTION_CHANGED_ONLY':int(learn_by_ver[1][5])==1 and int(learn_by_ver[1][6])==0 and float(learn_by_ver[1][3])>float(learn_by_ver[1][2]),
    'DUPLICATE_OUTCOME_BLOCKED':st_dup==409,
    'V2_FAILURE_CALLER_POSITIVE_DELTA_IGNORED':out2.get('caller_confidence_delta_ignored') is True and float(out2['computed_confidence_delta'])<0 and abs(float(out2['computed_confidence_delta'])-0.99)>0.5,
    'V2_OUTCOME_APPLIED_TO_CURRENT':out2.get('applied_to_current_item') is True and abs(float(item[0])-float(out2['version_confidence_after']))<1e-12,
    'V2_PROJECTION_MATCHES_ITEM':int(learn_by_ver[2][5])==0 and int(learn_by_ver[2][6])==1 and abs(float(learn_by_ver[2][3])-float(item[0]))<1e-12,
    'POLICY_VERSIONED':all(str(x[7])=='LP-1.0.0' for x in learning) and all(str(x[4])=='LP-1.0.0' for x in events),
    'LEARNING_EVENTS_VERSION_BOUND':len(events)==2 and str(event_by_app[app1['application_id']][2])==v1id and str(event_by_app[app2['application_id']][2])==v2id,
    'OUTCOME_STORES_COMPUTED_NOT_REQUESTED':abs(float(outcome_by_app[app1['application_id']][2])-float(out1['computed_confidence_delta']))<1e-12 and abs(float(outcome_by_app[app2['application_id']][2])-float(out2['computed_confidence_delta']))<1e-12,
    'CALLER_DELTA_NOT_STORED':all(abs(float(x[2]))<0.2 for x in outcomes),
    'POLICY_COMPONENTS_PROVE_SYSTEM_DECISION':all((dict(x[7] or {}).get('caller_delta_authoritative') is False) for x in events),
    'LEARNING_EVENT_APPEND_ONLY':learning_update_blocked,
    'POLICY_VERSION_APPEND_ONLY':policy_update_blocked,
    'LEARNING_API_OK':st_learning==200 and len(learning_api.get('versions') or [])==2,
    'LIFETIME_COUNTERS_AGGREGATE':int(item[1])==2 and int(item[2])==1 and int(item[3])==1,
}
failed=[k for k,v in checks.items() if not v]
proof={
    'generated_at':datetime.now(UTC).isoformat(),'item_id':item_id,'project':project,
    'v1_application':app1,'v1_outcome':out1,'v2_application':app2,'v2_outcome':out2,
    'confidence_v2_before_late_v1_outcome':confidence_v2_before_old,
    'confidence_v2_after_late_v1_outcome':confidence_v2_after_old,
    'schema_version':schema,'learning_api':learning_api,'checks':checks,'failed_checks':failed,
    'MEMORIA_PLUS_03_VERSION_BOUND_OUTCOME':'PASS' if not failed else 'FAIL',
    'MEMORIA_PLUS_04_LEARNING_POLICY_ENGINE':'PASS' if not failed else 'FAIL',
}
(ROOT/'evidence/MEMORIA_PLUS_P03_P04_PROOF.json').write_text(json.dumps(proof,indent=2,default=str),encoding='utf-8')
md='''# MEMORIA PLUS — P03/P04 Proof\n\n- P03 Version-bound Outcome Learning: **{p03}**\n- P04 Learning Policy Engine: **{p04}**\n- Item: `{item}`\n- V1 late outcome changed V2 confidence: **{changed}**\n- V1 caller requested delta: `-0.99`; computed: `{d1}`\n- V2 caller requested delta: `+0.99`; computed: `{d2}`\n- Policy: `LP-1.0.0`\n- Failed checks: `{failed}`\n'''.format(p03=proof['MEMORIA_PLUS_03_VERSION_BOUND_OUTCOME'],p04=proof['MEMORIA_PLUS_04_LEARNING_POLICY_ENGINE'],item=item_id,changed=confidence_v2_after_old!=confidence_v2_before_old,d1=out1['computed_confidence_delta'],d2=out2['computed_confidence_delta'],failed=failed)
(ROOT/'evidence/MEMORIA_PLUS_P03_P04_PROOF.md').write_text(md,encoding='utf-8')
print(json.dumps({'result':'PASS' if not failed else 'FAIL','failed':failed,'item_id':item_id,'v1_computed_delta':out1.get('computed_confidence_delta'),'v1_applied_current':out1.get('applied_to_current_item'),'v2_computed_delta':out2.get('computed_confidence_delta'),'v2_applied_current':out2.get('applied_to_current_item'),'duplicate_status':st_dup,'schema':schema},indent=2))
raise SystemExit(0 if not failed else 1)
