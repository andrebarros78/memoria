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
from psycopg import sql as pg_sql
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, r"C:\New Projet\MEMORIA-CLIENT-ADAPTER\src")
from memoria_client_adapter import (  # noqa: E402
    MemoryClientAdapter,
    WindowsDpapiCredentialProvider,
)

AUTH = Path(os.getenv("ProgramData", r"C:\ProgramData")) / "MemoriaPermanente" / "auth" / "clients" / "local-admin.dpapi"
BASE = "http://127.0.0.1:8787"
MIGRATION = ROOT / "migrations" / "0027_complete_bitemporality.sql"
MIGRATION_SHA = "c0335ef7d6b5f97c577cf49564375a0120fe7b5f97557ad5fc85cf1853a1609c"
client = MemoryClientAdapter(BASE, client_id="local-admin", credential_provider=WindowsDpapiCredentialProvider(AUTH))

parts=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip().split(':',4)
h,p,d,u,pw=parts
DSN=f'host={h} port={p} dbname={d} user={u} password={pw} connect_timeout=5'


def request(method: str, path: str, payload=None, headers=None):
    return client.request(method, path, payload=payload, headers=headers)


def unsigned_status(path: str) -> int:
    try:
        urllib.request.urlopen(BASE + path, timeout=5)  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
        return 200
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def memory_payload(ns: str, key: str, token: str, **temporal):
    return {
        "namespace": ns,
        "memory_key": key,
        "category": "FACT",
        "content": {"token": token, "key": key},
        "content_text": f"{token} {key}",
        "provenance": {"proof": "MEMORIA_PLUS_P12"},
        "confidence": 1.0,
        "source": "memoria-plus-p12-proof",
        "tags": ["MEMORIA PLUS", "P12_PROOF"],
        "memory_scope": "GLOBAL_USER",
        "sharing_scope": "SYSTEM_SHARED",
        **{k: iso(v) if isinstance(v, datetime) else v for k,v in temporal.items() if v is not None},
    }


def list_by_token(token: str, **params):
    query={"q":token,"limit":100,**{k:(iso(v) if isinstance(v,datetime) else v) for k,v in params.items() if v is not None}}
    return request("GET", "/v1/memories?" + urllib.parse.urlencode(query))


def selected_ids(token: str, ns: str, **params):
    payload={"query":token,"namespaces":[ns],"limit":20,**{k:(iso(v) if isinstance(v,datetime) else v) for k,v in params.items() if v is not None}}
    st, body=request("POST","/v1/context/retrieve",payload)
    rows=body.get("selected",[]) if isinstance(body,dict) else []
    return st,{str(x.get("item_id")) for x in rows}


def sqlstate_for(sql: str, params=()):
    with psycopg.connect(DSN,row_factory=dict_row) as conn:
        conn.execute("select set_config('app.current_tenant','__SYSTEM__',false)")
        conn.execute("select set_config('app.tenant_id','__SYSTEM__',false)")
        try:
            conn.execute(sql,params)
            conn.rollback()
            return None
        except psycopg.Error as exc:
            state=exc.sqlstate
            conn.rollback()
            return state


run=uuid.uuid4().hex[:12].upper()
ns=f"P12_PROOF_{run}"
token=f"P12_LATE_{run}"
checks: dict[str,bool]={}
details: dict[str,object]={}

st,health=request("GET","/health")
checks["api_0_20_0"]=st==200 and health.get("version")=="0.20.0"
checks["temporal_spec_requires_auth"]=unsigned_status("/v1/temporal-spec")==401
st,spec=request("GET","/v1/temporal-spec")
checks["temporal_spec_version"]=st==200 and spec.get("version")=="BT-1.0.0"
checks["five_temporal_dimensions"] = spec.get("dimensions",{}).get("occurred_at")=="REAL_WORLD_FACT_TIME" and spec.get("dimensions",{}).get("observed_at")=="KNOWLEDGE_TIME" and spec.get("dimensions",{}).get("valid_from")=="EFFECTIVE_VALIDITY_START" and spec.get("dimensions",{}).get("valid_to")=="EFFECTIVE_VALIDITY_END_EXCLUSIVE" and spec.get("dimensions",{}).get("created_at")=="PERSISTENCE_TIME_IMMUTABLE"
checks["created_at_not_validity_rule"]=spec.get("validity_rule")=="created_at is never used as valid_from"

# Late-arriving memory: fact time is weeks before system knowledge/persistence time.
clock=datetime.now(UTC)
occurred=clock-timedelta(days=30)
observed=clock-timedelta(seconds=2)
st,body=request("POST","/v1/memories",memory_payload(ns,"late",token,occurred_at=occurred,observed_at=observed,valid_from=occurred))
late_id=str(body.get("item_id") or "") if isinstance(body,dict) else ""
checks["late_memory_created"]=st==201 and bool(late_id)
st,listing=list_by_token(token)
rows=listing.get("items",[]) if isinstance(listing,dict) else []
late=next((x for x in rows if x.get("item_id")==late_id),None)
checks["late_memory_listed_current"]=st==200 and late is not None
if late:
    occurred_db=dt(late["occurred_at"]); observed_db=dt(late["observed_at"]); valid_from_db=dt(late["valid_from"]); created_db=dt(late["created_at"])
else:
    occurred_db=observed_db=valid_from_db=created_db=clock
checks["fact_time_preserved_exact"] = late is not None and occurred_db==occurred
checks["knowledge_time_preserved_exact"] = late is not None and observed_db==observed
checks["validity_start_preserved_exact"] = late is not None and valid_from_db==occurred
checks["persistence_time_independent"] = late is not None and created_db>observed_db>occurred_db and created_db!=valid_from_db

valid_inside=occurred+timedelta(hours=1)
known_before_created=created_db-timedelta(microseconds=1)
known_after_created=created_db+timedelta(seconds=1)
st,before=list_by_token(token,valid_at=valid_inside,known_at=known_before_created)
checks["transaction_time_before_persistence_hides_late_fact"] = st==200 and all(x.get("item_id")!=late_id for x in before.get("items",[]))
st,after=list_by_token(token,valid_at=valid_inside,known_at=known_after_created)
checks["transaction_time_after_persistence_reveals_late_fact"] = st==200 and any(x.get("item_id")==late_id for x in after.get("items",[]))
st,prevalid=list_by_token(token,valid_at=occurred-timedelta(seconds=1),known_at=known_after_created)
checks["valid_time_before_fact_hides_memory"] = st==200 and all(x.get("item_id")!=late_id for x in prevalid.get("items",[]))

st,ids=selected_ids(token,ns,valid_at=valid_inside,known_at=known_before_created)
checks["context_asof_before_persistence_hides_late_fact"] = st==200 and late_id not in ids
st,ids=selected_ids(token,ns,valid_at=valid_inside,known_at=known_after_created)
checks["context_asof_after_persistence_reveals_late_fact"] = st==200 and late_id in ids

# Closed validity interval: current time must not be confused with historical validity.
closed_token=f"P12_CLOSED_{run}"
closed_from=clock-timedelta(days=10)
closed_to=clock-timedelta(days=5)
closed_observed=clock-timedelta(seconds=1)
st,body=request("POST","/v1/memories",memory_payload(ns,"closed",closed_token,occurred_at=closed_from,observed_at=closed_observed,valid_from=closed_from,valid_to=closed_to))
closed_id=str(body.get("item_id") or "") if isinstance(body,dict) else ""
checks["closed_interval_memory_created"]=st==201 and bool(closed_id)
st,current=list_by_token(closed_token)
checks["closed_interval_hidden_now"] = st==200 and all(x.get("item_id")!=closed_id for x in current.get("items",[]))
# created_at is needed only as transaction-time; obtain it directly for the historical as-of query.
with psycopg.connect(DSN,row_factory=dict_row) as conn:
    conn.execute("select set_config('app.current_tenant','__SYSTEM__',false)")
    conn.execute("select set_config('app.tenant_id','__SYSTEM__',false)")
    closed_row=conn.execute("select created_at from memory_items where item_id=%s",(closed_id,)).fetchone()
closed_created=closed_row["created_at"].astimezone(UTC)
st,historical=list_by_token(closed_token,valid_at=closed_from+timedelta(days=1),known_at=closed_created+timedelta(seconds=1))
checks["closed_interval_visible_historically"] = st==200 and any(x.get("item_id")==closed_id for x in historical.get("items",[]))

# Revision stores its own explicit fact/knowledge/validity times; no created_at-derived validity.
rev_token=f"P12_REV_{run}"
rev1_occ=clock-timedelta(days=20); rev1_obs=clock-timedelta(seconds=1)
st,body=request("POST","/v1/memories",memory_payload(ns,"revision",rev_token,occurred_at=rev1_occ,observed_at=rev1_obs,valid_from=rev1_occ))
rev_id=str(body.get("item_id") or "") if isinstance(body,dict) else ""
rev2_occ=clock-timedelta(days=15); rev2_obs=datetime.now(UTC)-timedelta(milliseconds=100)
rev_payload={
    "content":{"token":rev_token,"revision":2},"content_text":f"{rev_token} revision 2",
    "provenance":{"proof":"MEMORIA_PLUS_P12"},"confidence":1.0,"source":"memoria-plus-p12-proof",
    "tags":["MEMORIA PLUS","P12_PROOF"],"expected_version":1,
    "occurred_at":iso(rev2_occ),"observed_at":iso(rev2_obs),"valid_from":iso(rev2_occ),
}
st,rev_body=request("POST",f"/v1/memories/{rev_id}/versions",rev_payload)
checks["revision_with_explicit_temporal_envelope"] = st==201 and rev_body.get("version_no")==2
st,versions=request("GET",f"/v1/memories/{rev_id}/versions")
vers=versions.get("versions",[]) if isinstance(versions,dict) else []
v2=next((x for x in vers if x.get("version_no")==2),None)
checks["version_fact_time_exact"] = st==200 and v2 is not None and dt(v2["occurred_at"])==rev2_occ
checks["version_validity_not_derived_from_created_at"] = v2 is not None and dt(v2["valid_from"])==rev2_occ and dt(v2["created_at"])!=dt(v2["valid_from"])

# Invalid API temporal envelopes fail closed.
invalid_base=memory_payload(ns,"invalid-naive",f"P12_INVALID_{run}")
invalid_base["occurred_at"]="2026-08-01T10:00:00"
st,_=request("POST","/v1/memories",invalid_base)
checks["naive_timestamp_rejected_422"]=st==422
bad=memory_payload(ns,"invalid-order",f"P12_INVALID_ORDER_{run}",occurred_at=clock,observed_at=clock-timedelta(seconds=1))
st,_=request("POST","/v1/memories",bad)
checks["observed_before_occurred_rejected_422"]=st==422
bad=memory_payload(ns,"invalid-validity",f"P12_INVALID_VALIDITY_{run}",occurred_at=occurred,observed_at=observed,valid_from=occurred,valid_to=occurred)
st,_=request("POST","/v1/memories",bad)
checks["invalid_validity_interval_rejected_422"]=st==422

# External conversation late event: sidecar and persisted SESSION memory must preserve same envelope.
conv_occ=clock-timedelta(days=45); conv_obs=datetime.now(UTC)-timedelta(seconds=1)
conv_ref=f"https://chatgpt.com/c/{uuid.uuid4()}"
conv_msg=f"p12-{run.lower()}"
conv_payload={
    "provider":"chatgpt","external_session_ref":conv_ref,"objective":"P12 late-event proof",
    "role":"user","text":f"P12 conversation late event {run}","message_id":conv_msg,"ordinal":0,
    "capture_source":"P12_PROOF","process_now":True,
    "occurred_at":iso(conv_occ),"observed_at":iso(conv_obs),"valid_from":iso(conv_occ),
}
st,conv=request("POST","/v1/conversation-ingestion/turn",conv_payload)
conv_memory=str(conv.get("memory_id") or "") if isinstance(conv,dict) else ""
conv_event=str(conv.get("event_id") or "") if isinstance(conv,dict) else ""
checks["late_conversation_ingested"] = st==201 and conv.get("status")=="PROCESSED" and bool(conv_memory) and bool(conv_event)
with psycopg.connect(DSN,row_factory=dict_row) as conn:
    conn.execute("select set_config('app.current_tenant','__SYSTEM__',false)")
    conn.execute("select set_config('app.tenant_id','__SYSTEM__',false)")
    side=conn.execute("select occurred_at,observed_at,valid_from,valid_to from conversation_ingestion_event_temporal where event_id=%s",(conv_event,)).fetchone()
    mem=conn.execute("select occurred_at,observed_at,valid_from,valid_to,memory_scope,memory_scope_ref from memory_items where item_id=%s",(conv_memory,)).fetchone()
checks["conversation_sidecar_preserves_fact_time"] = bool(side and side["occurred_at"].astimezone(UTC)==conv_occ and side["observed_at"].astimezone(UTC)==conv_obs and side["valid_from"].astimezone(UTC)==conv_occ)
checks["conversation_memory_inherits_same_envelope"] = bool(mem and mem["occurred_at"].astimezone(UTC)==conv_occ and mem["observed_at"].astimezone(UTC)==conv_obs and mem["valid_from"].astimezone(UTC)==conv_occ and mem["memory_scope"]=="SESSION")
divergent={**conv_payload,"observed_at":iso(conv_obs+timedelta(seconds=1))}
st,_=request("POST","/v1/conversation-ingestion/turn",divergent)
checks["conversation_temporal_replay_divergence_rejected"] = st==409

# Schema/repair/trigger/security evidence.
with psycopg.connect(DSN,row_factory=dict_row) as conn:
    conn.execute("select set_config('app.current_tenant','__SYSTEM__',false)")
    conn.execute("select set_config('app.tenant_id','__SYSTEM__',false)")
    meta={r['key']:r['value'] for r in conn.execute("select key,value from schema_meta where key in ('schema_version','bitemporal_version','bitemporal_contract_entities','bitemporal_fact_entities','bitemporal_legacy_memory_backfill_count')")}
    unclassified=conn.execute('select temporal_contract_unclassified_count() n').fetchone()['n']
    repairs=conn.execute('select count(*) n from bitemporal_legacy_repairs').fetchone()['n']
    impossible=0
    for r in conn.execute("select entity_name from temporal_entity_contracts where temporal_kind='BITEMPORAL' and storage_mode='INLINE'"):
        table=r['entity_name']
        query = pg_sql.SQL('select count(*) n from {} where observed_at < occurred_at or (valid_to is not null and valid_to <= valid_from) or occurred_at is null or observed_at is null or valid_from is null').format(pg_sql.Identifier(table))
        impossible += int(conn.execute(query).fetchone()['n'])
    triggers=conn.execute("select count(*) n from pg_trigger t join pg_class c on c.oid=t.tgrelid join temporal_entity_contracts x on x.entity_name=c.relname where x.temporal_kind='BITEMPORAL' and x.storage_mode='INLINE' and not t.tgisinternal and pg_get_triggerdef(t.oid) like '%normalize_bitemporal_insert%' and t.tgenabled='O'").fetchone()['n']
    inline_count=conn.execute("select count(*) n from temporal_entity_contracts where temporal_kind='BITEMPORAL' and storage_mode='INLINE'").fetchone()['n']
    side_rls=conn.execute("select relrowsecurity,relforcerowsecurity from pg_class where oid='conversation_ingestion_event_temporal'::regclass").fetchone()
    alias_mismatch=conn.execute('select count(*) n from memory_items where valid_to is distinct from valid_until').fetchone()['n']
    mig=conn.execute("select checksum_sha256 from schema_migrations where version='0027_complete_bitemporality'").fetchone()
checks["schema_memory_0_20_0"] = meta.get("schema_version")=="memory-0.20.0"
checks["schema_bt_1_0_0"] = meta.get("bitemporal_version")=="BT-1.0.0"
checks["all_temporal_tables_classified"] = int(unclassified)==0 and int(meta.get("bitemporal_contract_entities") or 0)==43
checks["thirty_bitemporal_entities"] = int(meta.get("bitemporal_fact_entities") or 0)==30
checks["five_legacy_clock_repairs_preserved"] = int(repairs)==5
checks["no_invalid_bitemporal_rows"] = impossible==0
checks["all_bitemporal_insert_triggers_enabled"] = int(triggers)==int(inline_count)==29
checks["conversation_sidecar_force_rls"] = bool(side_rls and side_rls['relrowsecurity'] and side_rls['relforcerowsecurity'])
checks["valid_to_valid_until_alias_exact"] = int(alias_mismatch)==0
checks["migration_0027_checksum_exact"] = bool(mig and mig['checksum_sha256']==MIGRATION_SHA and hashlib.sha256(MIGRATION.read_bytes()).hexdigest()==MIGRATION_SHA)

# Direct SQL bypasses fail closed.
clone_sql="""insert into memory_items(item_id,namespace,memory_key,category,content_json,content_text,provenance,confidence,source,source_version,tags,content_sha256,memory_scope,memory_scope_ref,sharing_scope,validation_status,governor_eligible,occurred_at,observed_at,valid_from,valid_to)
select %s,namespace,%s,category,content_json,content_text,provenance,confidence,source,source_version,tags,content_sha256,memory_scope,memory_scope_ref,sharing_scope,'UNVALIDATED',false,%s,%s,%s,%s from memory_items where item_id=%s"""
checks["sql_observed_before_occurred_rejected"] = sqlstate_for(clone_sql,(f"mem-p12-bad-{uuid.uuid4().hex}",f"bad-order-{run}",clock,clock-timedelta(seconds=1),clock,None,late_id))=="23514"
checks["sql_invalid_validity_rejected"] = sqlstate_for(clone_sql,(f"mem-p12-bad-{uuid.uuid4().hex}",f"bad-validity-{run}",occurred,observed,occurred,occurred,late_id))=="23514"
checks["temporal_contract_registry_immutable"] = sqlstate_for("update temporal_entity_contracts set rationale=rationale where entity_name='memory_items'")=="55000"

failed=[k for k,v in checks.items() if not v]
result={
    "result":"PASS" if not failed else "FAIL",
    "failed":failed,
    "checks":checks,
    "run":run,
    "schema":meta,
    "late_memory_id":late_id,
    "closed_memory_id":closed_id,
    "revision_memory_id":rev_id,
    "conversation_event_id":conv_event,
    "conversation_memory_id":conv_memory,
    "migration_0027_sha256":MIGRATION_SHA,
    "legacy_repairs":int(repairs),
}
(ROOT/'evidence').mkdir(exist_ok=True)
json_bytes=json.dumps(result,ensure_ascii=False,indent=2).encode('utf-8')
(ROOT/'evidence/MEMORIA_PLUS_P12_PROOF.json').write_bytes(json_bytes)
md=[
    '# MEMORIA PLUS P12 — Bitemporalidade completa','',
    f"- Resultado: **{result['result']}**",f"- Schema: `{meta.get('schema_version')}`",f"- Contrato: `{meta.get('bitemporal_version')}`",
    f"- Checks: `{sum(1 for v in checks.values() if v)}/{len(checks)}`",f"- Reparos históricos preservados: `{repairs}`",'',
    '## Contrato temporal','',
    '- `occurred_at`: tempo real do fato.','- `observed_at`: tempo de conhecimento.','- `valid_from/valid_to`: validade efetiva.','- `created_at`: tempo imutável de persistência.','',
    '## Checks','',
] + [f"- [{'x' if v else ' '}] `{k}`" for k,v in checks.items()]
(ROOT/'evidence/MEMORIA_PLUS_P12_PROOF.md').write_text('\n'.join(md)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if not failed else 1)
