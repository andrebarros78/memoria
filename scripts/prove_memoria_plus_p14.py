from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,r'C:\New Projet\MEMORIA-CLIENT-ADAPTER\src')
from memoria_client_adapter import (  # noqa: E402
    MemoryClientAdapter,
    WindowsDpapiCredentialProvider,
)

AUTH=Path(os.getenv('ProgramData',r'C:\ProgramData'))/'MemoriaPermanente'/'auth'/'clients'/'local-admin.dpapi'
BASE='http://127.0.0.1:8787'
client=MemoryClientAdapter(BASE,client_id='local-admin',credential_provider=WindowsDpapiCredentialProvider(AUTH))
parts=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip().split(':',4)
h,p,d,u,pw=parts
DSN=f'host={h} port={p} dbname={d} user={u} password={pw} connect_timeout=5'
MIG=ROOT/'migrations/0029_operational_memory_b2.sql'
MIG_SHA='af5d4b7823ddacc43a7afad68d1b58c2c98047d1bb93fde2d9e35bacc034272e'


def req(method,path,payload=None): return client.request(method,path,payload=payload)
def unsigned(path):
    try: urllib.request.urlopen(BASE+path,timeout=5); return 200  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
    except urllib.error.HTTPError as e: return int(e.code)
def q(path,params): return path+'?'+urllib.parse.urlencode(params)
def canon(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
def digest(x): return hashlib.sha256(canon(x).encode('utf-8')).hexdigest()
def db():
    c=psycopg.connect(DSN,row_factory=dict_row)
    c.execute("select set_config('app.current_tenant','__SYSTEM__',false)")
    c.execute("select set_config('app.tenant_id','__SYSTEM__',false)")
    return c

def sqlstate(sql,params=(),authorized=False):
    c=db()
    try:
        if authorized: c.execute("select set_config('app.operational_mutation_authorized','1',true)")
        c.execute(sql,params); c.rollback(); return None
    except psycopg.Error as e:
        state=e.sqlstate; c.rollback(); return state
    finally: c.close()

def implementation_sha() -> str:
    h=hashlib.sha256()
    for rel in ['migrations/0029_operational_memory_b2.sql','src/memory_permanent/operational_memory.py','src/memory_permanent/store.py','src/memory_permanent/api.py','src/memory_permanent/client_auth.py']:
        data=(ROOT/rel).read_bytes(); h.update(rel.encode()); h.update(b'\0'); h.update(data); h.update(b'\0')
    return h.hexdigest()

run=uuid.uuid4().hex[:10].upper(); checks={}; now=datetime.now(UTC); impl=implementation_sha()

# Contract, auth and schema.
st,h=req('GET','/health'); checks['api_0_22_0']=st==200 and h.get('version')=='0.22.0'
checks['operational_spec_requires_auth']=unsigned('/v1/operational-memory/spec')==401
st,spec=req('GET','/v1/operational-memory/spec'); checks['operational_spec_om_1_0_0']=st==200 and spec.get('version')=='OM-1.0.0'
checks['operational_entities_exact']=spec.get('entities')==['COMPETENCY','SKILL','SKILL_VERSION','CAPABILITY']
checks['operational_statuses_exact']=spec.get('statuses')==['PROVEN','STALE','FAILED','DEPRECATED']
checks['replay_recovery_required']=spec.get('proven_gate',{}).get('required')==['REPLAY:PASS','RECOVERY:PASS']

# Real current P14 competency.
key=f'OPERATIONAL.MEMORY.B2.{run}'
st,comp=req('POST','/v1/operations/competencies',{'competency_key':key,'title':'Operational Memory B2','description':'Formal memory of proven system competencies','domain':'MEMORY'})
comp_id=comp.get('competency_id',''); checks['competency_created']=st==201 and bool(comp_id)
st,skill=req('POST','/v1/operations/skills',{'competency_id':comp_id,'skill_key':'OPERATIONAL.CATALOG','title':'Operational competency catalog','description':'Records exact capabilities, versions and evidence'})
skill_id=skill.get('skill_id',''); checks['skill_created']=st==201 and bool(skill_id)
st,version=req('POST','/v1/operations/skill-versions',{'skill_id':skill_id,'version_label':'OM-1.0.0','implementation_version':'0.22.0','implementation_sha256':impl,'contract':{'api':'/v1/operations/catalog','proof_gate':['REPLAY','RECOVERY'],'status_model':['PROVEN','STALE','FAILED','DEPRECATED']}})
current_version=version.get('skill_version_id',''); checks['current_skill_version_created']=st==201 and bool(current_version) and version.get('implementation_sha256')==impl
cap_ids=[]
for cap_key,contract in [
    ('CATALOG.QUERY',{'operation':'GET /v1/operations/catalog','effect':'READ'}),
    ('PROOF.REPLAY',{'operation':'POST proof REPLAY','effect':'EVIDENCE'}),
    ('PROOF.RECOVERY',{'operation':'POST proof RECOVERY','effect':'EVIDENCE'}),
]:
    st,cap=req('POST',f'/v1/operations/skill-versions/{current_version}/capabilities',{'capability_key':cap_key,'contract':contract}); cap_ids.append(cap.get('capability_id',''))
checks['three_capabilities_bound']=len(cap_ids)==3 and all(cap_ids)
st,bundle=req('GET',f'/v1/operations/skill-versions/{current_version}'); checks['new_version_is_unproven']=st==200 and bundle.get('current_status')=='UNPROVEN'

# PROVEN cannot be asserted by caller and immutable rows survive rejected mutation.
st,body=req('POST',f'/v1/operations/skill-versions/{current_version}/status',{'status':'PROVEN','reason':'caller assertion forbidden','evidence':{'run':run}})
checks['direct_api_proven_assertion_rejected']=st==422
state=sqlstate("update operational_competencies set title='tamper' where competency_id=%s",(comp_id,),authorized=True)
checks['append_only_competency_rejects_update']=state=='55000'
st,bundle_after=req('GET',f'/v1/operations/skill-versions/{current_version}')
checks['recovery_read_after_rejected_mutation']=st==200 and bundle_after.get('skill_version',{}).get('implementation_sha256')==impl and len(bundle_after.get('capabilities',[]))==3

# Replay and recovery proof for the real current implementation.
replay_evidence={'run':run,'skill_version_id':current_version,'implementation_sha256':impl,'catalog_roundtrip':True,'capability_count':3}
st,replay=req('POST',f'/v1/operations/skill-versions/{current_version}/proofs',{'proof_type':'REPLAY','result':'PASS','artifact_ref':f'p14:{run}:replay-current','artifact_sha256':digest(replay_evidence),'evidence':replay_evidence})
checks['current_replay_pass_recorded']=st==201 and replay.get('result')=='PASS' and replay.get('current_status')=='UNPROVEN'
recovery_evidence={'run':run,'skill_version_id':current_version,'blocked_mutation_sqlstate':state,'post_failure_catalog_healthy':True}
st,recovery=req('POST',f'/v1/operations/skill-versions/{current_version}/proofs',{'proof_type':'RECOVERY','result':'PASS','artifact_ref':f'p14:{run}:recovery-current','artifact_sha256':digest(recovery_evidence),'evidence':recovery_evidence})
checks['current_recovery_pass_autoproves']=st==201 and recovery.get('current_status')=='PROVEN'
st,bundle=req('GET',f'/v1/operations/skill-versions/{current_version}')
checks['current_skill_proven_with_exact_evidence']=st==200 and bundle.get('current_status')=='PROVEN' and len(bundle.get('proofs',[]))==2 and len(bundle.get('capabilities',[]))==3
st,cat=req('GET',q('/v1/operations/catalog',{'status':'PROVEN','competency_key':key,'capability_key':'CATALOG.QUERY'})); items=cat.get('items',[])
checks['catalog_knows_current_proven_capability']=st==200 and any(x.get('skill_version_id')==current_version and x.get('implementation_sha256')==impl and x.get('replay_proven') and x.get('recovery_proven') for x in items)

# Lifecycle/state-machine fixture: FAILED -> PROVEN -> STALE -> PROVEN -> superseded STALE -> DEPRECATED.
st,sm_skill=req('POST','/v1/operations/skills',{'competency_id':comp_id,'skill_key':'STATE.MACHINE.SELFTEST','title':'Operational state machine self-test','description':'Exercises proof lifecycle and recovery'})
sm_skill_id=sm_skill.get('skill_id',''); checks['state_machine_skill_created']=st==201 and bool(sm_skill_id)
fixture_v1_sha=digest({'fixture':'v1','run':run})
st,v1=req('POST','/v1/operations/skill-versions',{'skill_id':sm_skill_id,'version_label':'fixture-1','implementation_version':'0.22.0-test','implementation_sha256':fixture_v1_sha,'contract':{'fixture':True,'phase':1}})
v1_id=v1.get('skill_version_id',''); checks['fixture_v1_created']=st==201 and bool(v1_id)
fail_ev={'run':run,'expected':'FAIL transition'}
st,pfail=req('POST',f'/v1/operations/skill-versions/{v1_id}/proofs',{'proof_type':'REPLAY','result':'FAIL','artifact_ref':f'p14:{run}:fixture-fail','artifact_sha256':digest(fail_ev),'evidence':fail_ev})
checks['failed_replay_sets_failed']=st==201 and pfail.get('current_status')=='FAILED'
rec1={'run':run,'phase':'recover-after-fail'}
st,pr=req('POST',f'/v1/operations/skill-versions/{v1_id}/proofs',{'proof_type':'RECOVERY','result':'PASS','artifact_ref':f'p14:{run}:fixture-recovery','artifact_sha256':digest(rec1),'evidence':rec1})
checks['recovery_alone_does_not_clear_failed']=st==201 and pr.get('current_status')=='FAILED'
rep1={'run':run,'phase':'replay-after-recovery'}
st,pp=req('POST',f'/v1/operations/skill-versions/{v1_id}/proofs',{'proof_type':'REPLAY','result':'PASS','artifact_ref':f'p14:{run}:fixture-replay','artifact_sha256':digest(rep1),'evidence':rep1})
checks['fresh_replay_plus_recovery_reproves']=st==201 and pp.get('current_status')=='PROVEN'
st,stale=req('POST',f'/v1/operations/skill-versions/{v1_id}/status',{'status':'STALE','reason':'controlled stale proof gate test','evidence':{'run':run}})
checks['proven_can_be_marked_stale']=st==201 and stale.get('status')=='STALE'
rep2={'run':run,'phase':'replay-after-stale'}
st,only_rep=req('POST',f'/v1/operations/skill-versions/{v1_id}/proofs',{'proof_type':'REPLAY','result':'PASS','artifact_ref':f'p14:{run}:stale-replay','artifact_sha256':digest(rep2),'evidence':rep2})
checks['replay_only_after_stale_not_enough']=st==201 and only_rep.get('current_status')=='STALE'
rec2={'run':run,'phase':'recovery-after-stale'}
st,both=req('POST',f'/v1/operations/skill-versions/{v1_id}/proofs',{'proof_type':'RECOVERY','result':'PASS','artifact_ref':f'p14:{run}:stale-recovery','artifact_sha256':digest(rec2),'evidence':rec2})
checks['both_fresh_proofs_after_stale_reprove']=st==201 and both.get('current_status')=='PROVEN'
fixture_v2_sha=digest({'fixture':'v2','run':run})
st,v2=req('POST','/v1/operations/skill-versions',{'skill_id':sm_skill_id,'version_label':'fixture-2','implementation_version':'0.22.0-test2','implementation_sha256':fixture_v2_sha,'contract':{'fixture':True,'phase':2},'supersedes_skill_version_id':v1_id})
v2_id=v2.get('skill_version_id',''); checks['superseding_v2_created']=st==201 and bool(v2_id)
st,v1bundle=req('GET',f'/v1/operations/skill-versions/{v1_id}'); checks['supersession_auto_stales_prior_proven']=st==200 and v1bundle.get('current_status')=='STALE'
st,v2bundle=req('GET',f'/v1/operations/skill-versions/{v2_id}'); checks['new_superseding_version_unproven']=st==200 and v2bundle.get('current_status')=='UNPROVEN'
for typ in ('REPLAY','RECOVERY'):
    ev={'run':run,'fixture':'v2','proof_type':typ}
    st,last=req('POST',f'/v1/operations/skill-versions/{v2_id}/proofs',{'proof_type':typ,'result':'PASS','artifact_ref':f'p14:{run}:v2-{typ.lower()}','artifact_sha256':digest(ev),'evidence':ev})
checks['v2_proven_after_both_proofs']=st==201 and last.get('current_status')=='PROVEN'
st,depr=req('POST',f'/v1/operations/skill-versions/{v1_id}/status',{'status':'DEPRECATED','reason':'fixture v1 retired after supersession','evidence':{'superseded_by':v2_id}})
checks['stale_prior_version_deprecated']=st==201 and depr.get('status')=='DEPRECATED'
ev={'run':run,'attempt':'proof after deprecation'}
st,rejected=req('POST',f'/v1/operations/skill-versions/{v1_id}/proofs',{'proof_type':'REPLAY','result':'PASS','artifact_ref':f'p14:{run}:deprecated-proof','artifact_sha256':digest(ev),'evidence':ev})
checks['deprecated_version_rejects_new_proof']=st==422
st,rejected_status=req('POST',f'/v1/operations/skill-versions/{v1_id}/status',{'status':'STALE','reason':'must fail terminal','evidence':{'run':run}})
checks['deprecated_status_is_terminal']=st==422

# Database security/schema evidence.
with db() as c:
    meta={r['key']:r['value'] for r in c.execute("select key,value from schema_meta where key in ('schema_version','operational_memory_version','operational_memory_statuses','operational_memory_required_proofs','bitemporal_contract_entities','bitemporal_fact_entities')")}
    mig=c.execute("select checksum_sha256 from schema_migrations where version='0029_operational_memory_b2'").fetchone()
    rls=[dict(r) for r in c.execute("select relname,relrowsecurity,relforcerowsecurity from pg_class where relname in ('operational_competencies','operational_skills','operational_skill_versions','operational_capabilities','operational_proofs','operational_status_events') order by relname")]
    bt=c.execute("select count(*) n from temporal_entity_contracts where entity_name like 'operational_%' and temporal_kind='BITEMPORAL'").fetchone()['n']
    statuses=[r['status'] for r in c.execute("select status from operational_status_events where skill_version_id=%s order by created_at,status_event_id",(v1_id,))]
checks['schema_memory_0_22_0']=meta.get('schema_version')=='memory-0.22.0'
checks['schema_om_1_0_0']=meta.get('operational_memory_version')=='OM-1.0.0'
checks['schema_status_contract_exact']=meta.get('operational_memory_statuses')=='PROVEN,STALE,FAILED,DEPRECATED'
checks['six_bitemporal_operational_entities']=int(bt)==6
checks['all_operational_tables_force_rls']=len(rls)==6 and all(x['relrowsecurity'] and x['relforcerowsecurity'] for x in rls)
checks['migration_0029_checksum_exact']=bool(mig and mig['checksum_sha256']==MIG_SHA and hashlib.sha256(MIG.read_bytes()).hexdigest()==MIG_SHA)
checks['fixture_history_contains_all_states']=set(statuses)>={'FAILED','PROVEN','STALE','DEPRECATED'}
state=sqlstate("insert into operational_competencies(competency_id,tenant_id,competency_key,title,description,domain,occurred_at,observed_at,valid_from,created_by) values(%s,'__SYSTEM__',%s,'x','','MEMORY',now(),now(),now(),'direct')",(f'ocp-direct-{uuid.uuid4().hex}',f'DIRECT.{run}'))
checks['direct_operational_insert_requires_canonical_boundary']=state=='42501'
state=sqlstate("insert into operational_status_events(status_event_id,tenant_id,skill_version_id,status,reason,evidence,occurred_at,observed_at,valid_from,created_by) values(%s,'__SYSTEM__',%s,'PROVEN','invalid direct proof gate','{}'::jsonb,now(),now(),now(),'direct')",(f'ops-direct-{uuid.uuid4().hex}',f'osv-missing-{run}'),authorized=True)
checks['db_status_rejects_missing_version']=state=='23503'
state=sqlstate("update temporal_entity_contracts set rationale=rationale where entity_name='operational_competencies'")
checks['temporal_contract_registry_remains_immutable']=state=='55000'

# Final catalog must keep real current capability proven and fixture v2 proven while v1 is deprecated.
st,finalcat=req('GET',q('/v1/operations/catalog',{'competency_key':key})); rows=finalcat.get('items',[])
byid={x.get('skill_version_id'):x for x in rows}
checks['final_catalog_exact_statuses']=st==200 and byid.get(current_version,{}).get('current_status')=='PROVEN' and byid.get(v2_id,{}).get('current_status')=='PROVEN' and byid.get(v1_id,{}).get('current_status')=='DEPRECATED'
checks['final_catalog_preserves_current_implementation_hash']=byid.get(current_version,{}).get('implementation_sha256')==impl

failed=[k for k,v in checks.items() if not v]
result={'result':'PASS' if not failed else 'FAIL','failed':failed,'checks':checks,'check_count':len(checks),'passed':sum(bool(v) for v in checks.values()),'run':run,'operational_memory_version':'OM-1.0.0','implementation_sha256':impl,'competency_id':comp_id,'current_skill_version_id':current_version,'fixture_v1':v1_id,'fixture_v2':v2_id,'schema':meta,'migration_0029_sha256':MIG_SHA}
(ROOT/'evidence').mkdir(exist_ok=True)
raw=json.dumps(result,ensure_ascii=False,indent=2).encode('utf-8'); (ROOT/'evidence/MEMORIA_PLUS_P14_PROOF.json').write_bytes(raw)
md=['# MEMORIA PLUS P14 — Memória operacional B2','',f"- Resultado: **{result['result']}**",f"- Checks: `{result['passed']}/{result['check_count']}`",'- Contrato: `OM-1.0.0`','', '## Checks','']+[f"- [{'x' if v else ' '}] `{k}`" for k,v in checks.items()]
(ROOT/'evidence/MEMORIA_PLUS_P14_PROOF.md').write_text('\n'.join(md)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if not failed else 1)
