from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
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
MIG=ROOT/'migrations/0028_economic_memory.sql'
MIG_SHA='6bbd7623c8b46409287f2897f634b9ffd4035694920d1250d041ee7ab71414f3'

def req(method,path,payload=None): return client.request(method,path,payload=payload)
def iso(x): return x.astimezone(UTC).isoformat()
def unsigned(path):
    try: urllib.request.urlopen(BASE+path,timeout=5); return 200  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
    except urllib.error.HTTPError as e: return int(e.code)
def q(path,params): return path+'?'+urllib.parse.urlencode(params)
def db():
    c=psycopg.connect(DSN,row_factory=dict_row)
    c.execute("select set_config('app.current_tenant','__SYSTEM__',false)")
    c.execute("select set_config('app.tenant_id','__SYSTEM__',false)")
    return c

def sqlstate(sql,params=()):
    c=db()
    try:
        c.execute(sql,params); c.rollback(); return None
    except psycopg.Error as e:
        s=e.sqlstate; c.rollback(); return s
    finally: c.close()

run=uuid.uuid4().hex[:10].upper(); mission=f'P13-ECO-{run}'; checks={}; now=datetime.now(UTC)
t0=now-timedelta(days=30); t1=t0+timedelta(minutes=1); t2=t0+timedelta(minutes=2); t3=t0+timedelta(minutes=3); t4=t0+timedelta(minutes=4); t5=t0+timedelta(minutes=5)
obs=now-timedelta(seconds=3)

st,h=req('GET','/health'); checks['api_0_21_0']=st==200 and h.get('version')=='0.21.0'
checks['economic_spec_requires_auth']=unsigned('/v1/economic-memory/spec')==401
st,spec=req('GET','/v1/economic-memory/spec'); checks['economic_spec_em_1_0_0']=st==200 and spec.get('version')=='EM-1.0.0'
checks['economic_domain_complete']=set(spec.get('entity_types',[]))=={'PRODUCT','SKU','CAMPAIGN','AD'} and set(spec.get('state_types',[]))=={'INVENTORY','MARGIN','CAPITAL'}

# Sovereign mission anchor and evidence memory.
st,cp=req('POST','/v1/checkpoints',{'namespace':'P13_PROOF','mission_id':mission,'step_index':1,'state':{'objective':'prove economic attribution','run':run},'occurred_at':iso(t0),'observed_at':iso(obs),'valid_from':iso(t0)})
checks['mission_checkpoint_created']=st==201 and bool(cp.get('checkpoint_id'))
ev_payload={'namespace':'P13_PROOF','memory_key':f'evidence-{run}','category':'EVIDENCE','content':{'run':run,'evidence':'campaign experiment'},'content_text':f'P13 evidence {run}','provenance':{'proof':'P13'},'confidence':1.0,'source':'p13-proof','tags':['MEMORIA PLUS','P13'],'memory_scope':'MISSION','memory_scope_ref':mission,'sharing_scope':'SYSTEM_SHARED','occurred_at':iso(t1),'observed_at':iso(obs),'valid_from':iso(t1)}
st,ev=req('POST','/v1/memories',ev_payload); evidence_item=ev.get('item_id',''); checks['evidence_memory_created']=st==201 and bool(evidence_item)
st,vers=req('GET',f'/v1/memories/{evidence_item}/versions'); v1=vers.get('versions',[{}])[0]; evidence_version=v1.get('version_id','')

# Formal decision.
dec_payload={'mission_id':mission,'criticality':'HIGH','objective':'increase profitable campaign scale','context':{'run':run},'alternatives':[{'id':'A','label':'scale campaign'},{'id':'B','label':'hold spend'}],'rationale':'evidence supports controlled scale','action':{'type':'CAMPAIGN_SCALE','target':f'campaign-{run}','parameters':{'delta_percent':20}},'expected_outcome':{'profit_delta':'positive'},'proof':{'run':run},'evidence_refs':[{'item_id':evidence_item,'version_id':evidence_version,'role':'EVIDENCE'}],'occurred_at':iso(t2)}
st,dec=req('POST','/v1/decisions',dec_payload); decision_id=dec.get('decision_id',''); checks['sovereign_decision_created']=st==201 and bool(decision_id)

# Experience graph chain: evidence -> decision -> intervention -> result.
def node(kind,ref,when,**extra):
    payload={'node_type':kind,'entity_ref':ref,'payload':{'run':run},'provenance':{'proof':'P13'},'occurred_at':iso(when),**extra}
    return req('POST',f'/v1/experience/missions/{mission}/nodes',payload)
st,en=node('EVIDENCE',f'evidence-node-{run}',t1,memory_item_id=evidence_item,memory_version_id=evidence_version); evidence_node=en.get('node_id',''); checks['experience_evidence_node']=st==201 and bool(evidence_node)
st,dn=node('DECISION',decision_id,t2); decision_node=dn.get('node_id','')
st,inn=node('INTERVENTION',f'intervention-{run}',t3); intervention_node=inn.get('node_id',''); checks['experience_intervention_node']=st==201 and bool(intervention_node)
st,rn=node('RESULT',f'result-{run}',t4); result_node=rn.get('node_id',''); checks['experience_result_node']=st==201 and bool(result_node)
def edge(a,rel,b,when): return req('POST',f'/v1/experience/missions/{mission}/edges',{'from_node_id':a,'relation_type':rel,'to_node_id':b,'evidence':{'run':run},'occurred_at':iso(when)})
checks['graph_edge_evidence_decision']=edge(evidence_node,'INFORMS',decision_node,t2)[0]==201
checks['graph_edge_decision_intervention']=edge(decision_node,'IMPLEMENTED_BY',intervention_node,t3)[0]==201
checks['graph_edge_intervention_result']=edge(intervention_node,'PRODUCES',result_node,t4)[0]==201

# Economic ontology entities.
def entity(kind,ref,parent=None):
    return req('POST','/v1/economy/entities',{'entity_type':kind,'external_ref':ref,'parent_entity_id':parent,'attributes':{'run':run},'occurred_at':iso(t0),'observed_at':iso(obs),'valid_from':iso(t0)})
st,product=entity('PRODUCT',f'product-{run}'); product_id=product.get('economic_entity_id',''); checks['product_created']=st==201
st,sku=entity('SKU',f'sku-{run}',product_id); sku_id=sku.get('economic_entity_id',''); checks['sku_created_with_product_parent']=st==201 and sku.get('parent_entity_id')==product_id
st,camp=entity('CAMPAIGN',f'campaign-{run}'); campaign_id=camp.get('economic_entity_id',''); checks['campaign_created']=st==201
st,ad=entity('AD',f'ad-{run}',campaign_id); ad_id=ad.get('economic_entity_id',''); checks['ad_created_with_campaign_parent']=st==201 and ad.get('parent_entity_id')==campaign_id
# Invalid hierarchy must fail closed.
st,_=entity('SKU',f'bad-sku-{run}',campaign_id); checks['invalid_economic_parent_rejected']=st==422

# Inventory, margin, capital state.
def state(eid,kind,value,unit,currency=None):
    return req('POST','/v1/economy/states',{'economic_entity_id':eid,'mission_id':mission,'state_type':kind,'value':value,'unit':unit,'currency':currency,'metadata':{'run':run},'occurred_at':iso(t3),'observed_at':iso(obs),'valid_from':iso(t3)})
st,inv=state(sku_id,'INVENTORY','125','UNITS'); inventory_state=inv.get('economic_state_id',''); checks['inventory_state_created']=st==201 and inv.get('value')=='125'
st,margin=state(sku_id,'MARGIN','37.45','PERCENT'); margin_state=margin.get('economic_state_id',''); checks['margin_state_created']=st==201 and margin.get('value')=='37.45'
st,capital=state(campaign_id,'CAPITAL','5000.00','MONEY','BRL'); capital_state=capital.get('economic_state_id',''); checks['capital_state_created']=st==201 and capital.get('currency')=='BRL'

# Economic result attributed to decision, intervention, evidence, capital and campaign.
attrs=[
 {'source_kind':'SOVEREIGN_DECISION','source_id':decision_id,'weight':'0.30','rationale':'decision allocation','evidence':{'run':run}},
 {'source_kind':'EXPERIENCE_INTERVENTION','source_id':intervention_node,'weight':'0.25','rationale':'implemented scale','evidence':{'run':run}},
 {'source_kind':'EXPERIENCE_EVIDENCE','source_id':evidence_node,'weight':'0.20','rationale':'experimental evidence','evidence':{'run':run}},
 {'source_kind':'ECONOMIC_STATE','source_id':capital_state,'weight':'0.15','rationale':'capital deployed','evidence':{'run':run}},
 {'source_kind':'ECONOMIC_ENTITY','source_id':campaign_id,'weight':'0.10','rationale':'campaign object','evidence':{'run':run}},
]
res_payload={'mission_id':mission,'economic_entity_id':campaign_id,'metric_type':'PROFIT','value':'1234.56','unit':'MONEY','currency':'BRL','experience_result_node_id':result_node,'proof':{'source':'ledger','run':run},'attributions':attrs,'occurred_at':iso(t5),'observed_at':iso(obs),'valid_from':iso(t5)}
st,res=req('POST','/v1/economy/results',res_payload); economic_result=res.get('economic_result_id',''); checks['economic_result_created']=st==201 and res.get('attribution_count')==5 and res.get('value')=='1234.56'
if st != 201: print(json.dumps({'economic_result_status':st,'body':res,'checks_so_far':checks},ensure_ascii=False,indent=2)); raise SystemExit(2)
st,bundle=req('GET',f'/v1/economy/results/{economic_result}'); at=bundle.get('attributions',[]); checks['five_attribution_snapshots']=st==200 and len(at)==5 and all(len(x.get('source_sha256',''))==64 and isinstance(x.get('source_snapshot'),dict) and x.get('source_snapshot') for x in at)
checks['attribution_weight_total_exact']=sum(float(x.get('weight','0')) for x in at)==1.0
dec_attr=next((x for x in at if x.get('source_kind')=='SOVEREIGN_DECISION'),{}); dec_snap=dec_attr.get('source_snapshot') or {}; checks['decision_attribution_snapshot_exact']=dec_snap.get('decision_id')==decision_id and len(str(dec_snap.get('core_sha256') or ''))==64
checks['experience_result_binding_exact']=bundle.get('result',{}).get('experience_result_node_id')==result_node

# Snapshot remains exact even if source evidence memory is revised later.
ev_attr=next((x for x in at if x.get('source_kind')=='EXPERIENCE_EVIDENCE'),{}); snap_sha=ev_attr.get('source_sha256'); snap_ver=(ev_attr.get('source_snapshot') or {}).get('memory_version_id')
rev={'content':{'run':run,'evidence':'revised later'},'content_text':f'P13 revised evidence {run}','provenance':{'proof':'P13'},'confidence':1.0,'source':'p13-proof','tags':['MEMORIA PLUS','P13'],'expected_version':1,'occurred_at':iso(t5+timedelta(minutes=1)),'observed_at':iso(now-timedelta(seconds=1)),'valid_from':iso(t5+timedelta(minutes=1))}
st,_=req('POST',f'/v1/memories/{evidence_item}/versions',rev); checks['source_evidence_revised_after_result']=st==201
st,bundle2=req('GET',f'/v1/economy/results/{economic_result}'); ev_attr2=next((x for x in bundle2.get('attributions',[]) if x.get('source_kind')=='EXPERIENCE_EVIDENCE'),{}); checks['attribution_snapshot_survives_source_revision']=ev_attr2.get('source_sha256')==snap_sha and (ev_attr2.get('source_snapshot') or {}).get('memory_version_id')==snap_ver==evidence_version

# Bitemporal as-of: knowledge before persistence hides result, after persistence reveals it.
created=datetime.fromisoformat(bundle2['result']['created_at']).astimezone(UTC)
params={'economic_entity_id':campaign_id,'mission_id':mission,'valid_at':iso(t5+timedelta(seconds=1)),'known_at':iso(created-timedelta(microseconds=1))}
st,hist_before=req('GET',q('/v1/economy/history',params)); checks['economic_result_hidden_before_persistence']=st==200 and all(x.get('economic_result_id')!=economic_result for x in hist_before.get('results',[]))
params['known_at']=iso(created+timedelta(seconds=1)); st,hist_after=req('GET',q('/v1/economy/history',params)); checks['economic_result_visible_after_persistence']=st==200 and any(x.get('economic_result_id')==economic_result for x in hist_after.get('results',[]))

# Database security and schema evidence.
with db() as c:
    meta={r['key']:r['value'] for r in c.execute("select key,value from schema_meta where key in ('schema_version','economic_memory_version','bitemporal_version')")}
    mig=c.execute("select checksum_sha256 from schema_migrations where version='0028_economic_memory'").fetchone()
    rls=c.execute("select relname,relrowsecurity,relforcerowsecurity from pg_class where relname in ('economic_entities','economic_states','economic_results','economic_attributions') and relkind='r' order by relname").fetchall()
    triggers=c.execute("select count(*) n from pg_trigger t join pg_class c on c.oid=t.tgrelid where c.relname in ('economic_entities','economic_states','economic_results','economic_attributions') and not t.tgisinternal and t.tgenabled='O'").fetchone()['n']
checks['schema_memory_0_21_0']=meta.get('schema_version')=='memory-0.21.0'
checks['schema_em_1_0_0']=meta.get('economic_memory_version')=='EM-1.0.0'
checks['bitemporal_bt_1_0_0_preserved']=meta.get('bitemporal_version')=='BT-1.0.0'
checks['migration_0028_exact']=bool(mig and mig['checksum_sha256']==MIG_SHA and hashlib.sha256(MIG.read_bytes()).hexdigest()==MIG_SHA)
checks['economic_tables_force_rls']=len(rls)==4 and all(x['relrowsecurity'] and x['relforcerowsecurity'] for x in rls)
checks['economic_security_triggers_enabled']=int(triggers)>=16
# Direct SQL writes/mutations outside canonical boundary fail.
checks['direct_economic_insert_rejected']=sqlstate("insert into economic_entities(economic_entity_id,tenant_id,entity_type,external_ref,attributes,occurred_at,observed_at,valid_from,created_by) values(%s,'__SYSTEM__','PRODUCT',%s,'{}'::jsonb,now(),now(),now(),'sql')",(f'eco-bad-{run}',f'bad-{run}'))=='42501'
checks['economic_append_only_rejected']=sqlstate("update economic_results set value=value where economic_result_id=%s",(economic_result,))=='55000'
# Attribution total >1 must be rejected at API/domain boundary.
bad={**res_payload,'attributions':[{'source_kind':'ECONOMIC_ENTITY','source_id':campaign_id,'weight':'0.7'},{'source_kind':'ECONOMIC_STATE','source_id':capital_state,'weight':'0.4'}]}
st,_=req('POST','/v1/economy/results',bad); checks['over_attribution_rejected']=st==422
# Cross-type attribution rejected.
bad2={**res_payload,'attributions':[{'source_kind':'EXPERIENCE_EVIDENCE','source_id':intervention_node,'weight':'1.0'}]}
st,_=req('POST','/v1/economy/results',bad2); checks['wrong_experience_attribution_type_rejected']=st==422

failed=[k for k,v in checks.items() if not v]
out={'result':'PASS' if not failed else 'FAIL','failed':failed,'checks':checks,'run':run,'mission_id':mission,'decision_id':decision_id,'economic_result_id':economic_result,'entities':{'product':product_id,'sku':sku_id,'campaign':campaign_id,'ad':ad_id},'states':{'inventory':inventory_state,'margin':margin_state,'capital':capital_state},'experience':{'evidence':evidence_node,'decision':decision_node,'intervention':intervention_node,'result':result_node},'schema':meta,'migration_0028_sha256':MIG_SHA}
(ROOT/'evidence').mkdir(exist_ok=True)
(ROOT/'evidence/MEMORIA_PLUS_P13_PROOF.json').write_bytes(json.dumps(out,ensure_ascii=False,indent=2).encode('utf-8'))
md=['# MEMORIA PLUS P13 — Memória econômica','',f"- Resultado: **{out['result']}**",f"- Checks: `{sum(checks.values())}/{len(checks)}`",f"- Schema: `{meta.get('schema_version')}`",f"- Ontologia econômica: `{meta.get('economic_memory_version')}`",'', '## Checks','']+[f"- [{'x' if v else ' '}] `{k}`" for k,v in checks.items()]
(ROOT/'evidence/MEMORIA_PLUS_P13_PROOF.md').write_text('\n'.join(md)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(out,ensure_ascii=False,indent=2))
raise SystemExit(0 if not failed else 1)
