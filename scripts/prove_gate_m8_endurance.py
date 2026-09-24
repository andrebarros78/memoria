from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from memory_permanent.access_policy import AgentAccessContext
from memory_permanent.store import PostgresMemoryStore


def require(condition: object, detail: object = "proof assertion failed") -> None:
    if not condition:
        raise RuntimeError(f"proof requirement failed: {detail!r}")


ROOT=Path(__file__).resolve().parents[1]
API="http://127.0.0.1:8787"

def http(method,path,payload=None,timeout=15):
    data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode()
    req=urllib.request.Request(API+path,data=data,method=method,headers={"Accept":"application/json","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as r:  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
        return r.status,r.read().decode()

def dsn():
    h,p,d,u,w=(ROOT/"runtime/secrets/pgpass.conf").read_text(encoding="ascii").strip().split(":",4)
    return f"host={h} port={p} dbname={d} user={u} password={w} connect_timeout=5"

def ctx(conn):
    conn.execute("SELECT set_config('app.current_tenant',%s,true)",("LEGACY",))
    conn.execute("SELECT set_config('app.current_agent',%s,true)",("__SYSTEM__",))

def metric(text,name):
    for line in text.splitlines():
        if line.startswith(name+" "):
            try:return float(line.split(None,1)[1])
            except:return None
    return None

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--duration-seconds",type=int,default=90); ap.add_argument("--max-writes",type=int,default=500)
    a=ap.parse_args(); duration=max(30,min(a.duration_seconds,240)); maxw=max(100,min(a.max_writes,1000))
    suf=f"{int(time.time())}-{uuid.uuid4().hex[:8]}"; ns=f"M8_ENDURANCE_{suf}".upper(); mission=f"m8-endurance-{suf}"; marker=f"M8_EVENT_MARKER_{suf}"
    ids=[]; errors=[]; reads=healths=metrics_n=cps=0
    _,hr=http("GET","/health"); hb=json.loads(hr); _,mb=http("GET","/metrics")
    D=dsn()
    with psycopg.connect(D,row_factory=dict_row,connect_timeout=5) as c:
        with c.transaction():
            ctx(c); start=c.execute("SELECT (SELECT count(*) FROM memory_events) events,(SELECT count(*) FROM memory_items) items,(SELECT count(*) FROM memory_outbox) outbox").fetchone()
    t0=time.monotonic(); i=0; nextcp=25
    while time.monotonic()-t0<duration:
        try:
            if i<maxw:
                payload={"namespace":ns,"memory_key":f"m8-{i:05d}","category":"EVIDENCE","content":{"gate":"M8","index":i,"marker":marker},"content_text":f"{marker} durable event {i}","provenance":{"trusted":True,"proof":"GATE_M8_ENDURANCE","index":i},"confidence":1.0,"source":"sovereign-system","source_version":"M8-ENDURANCE","tags":["GATE_M8","ENDURANCE",marker],"changed_by":"prove_gate_m8_endurance","sharing_scope":"SYSTEM_SHARED"}
                st,raw=http("POST","/v1/memories",payload); require(st == 201, 'prove_gate_m8_endurance.py:58')
                ids.append(str(json.loads(raw)["item_id"])); i+=1
                if i>=nextcp:
                    st,_=http("POST","/v1/checkpoints",{"namespace":ns,"mission_id":mission,"step_index":i,"state":{"phase":"ENDURANCE_ACTIVE","writes_confirmed":i,"last_item_id":ids[-1],"marker":marker,"next_safe_action":"continue-endurance"}}); require(st == 201, 'prove_gate_m8_endurance.py:61')
                    cps+=1; nextcp+=25
            q=urllib.parse.quote(marker,safe=""); st,raw=http("GET",f"/v1/memories?q={q}&limit=5")
            if st==200 and any(marker in str(x.get("content_text") or "") for x in (json.loads(raw).get("items") or [])): reads+=1
            if i%10==0:
                st,raw=http("GET","/health"); healths+=int(st==200 and json.loads(raw).get("status")=="ok")
                st,raw=http("GET","/metrics"); metrics_n+=int(st==200 and "memory_service_up 1" in raw)
            if i>=maxw: time.sleep(.05)
        except (AssertionError, OSError, RuntimeError, ValueError) as e:
            errors.append({"i":i,"type":type(e).__name__,"message":str(e)[:200]}); time.sleep(.05)
    elapsed=time.monotonic()-t0
    _,ma=http("GET","/metrics"); _,ha_raw=http("GET","/health"); ha=json.loads(ha_raw)
    powershell=shutil.which("powershell.exe")
    if not powershell: raise RuntimeError("powershell.exe is not available")
    b=subprocess.run([powershell,"-NoProfile","-ExecutionPolicy","Bypass","-File",str(ROOT/"scripts/backup_memory.ps1")],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=120)  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.
    bj={}
    if b.returncode==0:
        txt=b.stdout.strip()
        try: bj=json.loads(txt[txt.find("{"):txt.rfind("}")+1])
        except: bj={"parse_failed":True}
    with psycopg.connect(D,row_factory=dict_row,connect_timeout=5) as c:
        with c.transaction():
            ctx(c)
            final=c.execute("SELECT (SELECT count(*) FROM memory_events) events,(SELECT count(*) FROM memory_items) items,(SELECT count(*) FROM memory_outbox) outbox").fetchone()
            pi=c.execute("SELECT count(*) n FROM memory_items WHERE item_id=ANY(%s)",(ids,)).fetchone()
            pe=c.execute("SELECT count(*) n,count(DISTINCT event_id) u FROM memory_events WHERE item_id=ANY(%s) AND event_type='MEMORY_CREATED'",(ids,)).fetchone()
            po=c.execute("SELECT count(*) n FROM memory_outbox o JOIN memory_events e ON e.event_id=o.event_id WHERE e.item_id=ANY(%s) AND e.event_type='MEMORY_CREATED'",(ids,)).fetchone()
            cp=c.execute("SELECT checkpoint_id,step_index,state_sha256 FROM checkpoints WHERE mission_id=%s ORDER BY step_index DESC,created_at DESC LIMIT 1",(mission,)).fetchone()
    audit=PostgresMemoryStore(D,initialize=False,tenant_id="LEGACY",access=AgentAccessContext.system()).verify_audit_chain()
    n=len(ids)
    checks={"API_VERSION_0_8_1":hb.get("version")=="0.8.1" and ha.get("version")=="0.8.1","ENDURANCE_DURATION_REACHED":elapsed>=duration*.98,"AT_LEAST_100_WRITES":n>=100,"ZERO_OPERATION_ERRORS":not errors,"READS_CONFIRMED":reads>0,"HEALTH_CHECKS_CONFIRMED":healths>0,"METRICS_CHECKS_CONFIRMED":metrics_n>0,"ALL_CREATED_ITEMS_PRESENT":int(pi["n"] or 0)==n,"ALL_CREATED_EVENTS_PRESENT":int(pe["n"] or 0)==n,"CREATED_EVENT_IDS_UNIQUE":int(pe["u"] or 0)==n,"OUTBOX_EVENT_PARITY":int(po["n"] or 0)==n,"CHECKPOINTS_PERSISTED":cps>0 and cp is not None,"EVENT_COUNTER_GREW":int(final["events"])>=int(start["events"])+n,"ITEM_COUNTER_GREW":int(final["items"])>=int(start["items"])+n,"OUTBOX_COUNTER_GREW":int(final["outbox"])>=int(start["outbox"])+n,"METRICS_AVAILABLE_BEFORE":metric(mb,"memory_service_up")==1.0,"METRICS_AVAILABLE_AFTER":metric(ma,"memory_service_up")==1.0,"METRICS_AUDIT_NONDECREASING":(metric(ma,"memory_audit_events_total") or 0)>=(metric(mb,"memory_audit_events_total") or 0),"BACKUP_COMMAND_PASS":b.returncode==0,"BACKUP_VALID":bool(bj.get("backup_valid")),"BACKUP_SHA256_VALID":len(str(bj.get("sha256") or ""))==64,"AUDIT_CHAIN_VALID":bool(audit.get("ok"))}
    failed=[k for k,v in checks.items() if not v]
    result={"generated_at":datetime.now().astimezone().isoformat(),"gate":"M8","mode":"CONTROLLED_LOCAL_ENDURANCE","requested_duration_seconds":duration,"elapsed_seconds":round(elapsed,3),"writes_created":n,"confirmed_reads":reads,"health_checks":healths,"metric_checks":metrics_n,"checkpoints":cps,"namespace":ns,"mission_id":mission,"start_counts":dict(start),"final_counts":dict(final),"proof_counts":{"items":int(pi["n"] or 0),"events":int(pe["n"] or 0),"unique_event_ids":int(pe["u"] or 0),"outbox":int(po["n"] or 0)},"latest_checkpoint":dict(cp) if cp else None,"backup":bj,"audit":audit,"errors":errors,"checks":checks,"failed_checks":failed,"GATE_M8":"PASS" if not failed else "FAIL","CONTINUOUS_OPERATION_PROVEN":not failed,"EVENT_LOSS_DETECTED":int(pe["n"] or 0)!=n or int(po["n"] or 0)!=n}
    ev=ROOT/"evidence"; ev.mkdir(exist_ok=True); (ev/"M8_GATE_PROOF.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    print(json.dumps({"GATE_M8":result["GATE_M8"],"elapsed_seconds":result["elapsed_seconds"],"writes_created":n,"events_confirmed":result["proof_counts"]["events"],"outbox_confirmed":result["proof_counts"]["outbox"],"backup_valid":bool(bj.get("backup_valid")),"audit_ok":bool(audit.get("ok")),"failed":failed},ensure_ascii=False,indent=2))
    return 0 if not failed else 1

if __name__=="__main__": raise SystemExit(main())
