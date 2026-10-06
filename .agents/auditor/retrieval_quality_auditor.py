from __future__ import annotations

import argparse
import ctypes
import hashlib
import hmac
import json
import os
import secrets
import subprocess  # nosec B404 -- OPA is a fixed canonical local executable; shell execution is not used.
import sys
import time
import urllib.error
import urllib.request
import uuid
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents import Agent
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes
from phoenix.otel import register

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = PROJECT_ROOT / "src"
if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))
from memory_permanent.network_policy import (  # noqa: E402
    HTTP_ERROR_RESPONSE_MAX_BYTES,
    MEMORY_API_RESPONSE_MAX_BYTES,
    open_url_no_redirect,
    read_http_response_limited,
    validate_loopback_service_base_url,
    validate_origin_relative_path_query,
)

AUTH_ENTROPY=b"MEMORIA-PERMANENTE:CLIENT-AUTH:V1"
AUTH_ROOT=Path(r"C:\ProgramData\MemoriaPermanente\auth")
OPA=Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0\.agents\tools\opa\opa.exe")
ROOT=Path(__file__).resolve().parent
POLICY=ROOT/"policy"/"retrieval_auditor.rego"
POLICY_ROOT=ROOT/"policy"
BASELINES=ROOT/"baselines"
RUNS=ROOT/"runs"
PHOENIX="http://127.0.0.1:6006"
class _DATA_BLOB(ctypes.Structure):
    _fields_=[("cbData",wintypes.DWORD),("pbData",ctypes.POINTER(ctypes.c_byte))]
def _blob(data:bytes):
    buf=ctypes.create_string_buffer(data); return _DATA_BLOB(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_byte))),buf
def dpapi_unprotect(data:bytes)->bytes:
    crypt32=ctypes.windll.crypt32; kernel32=ctypes.windll.kernel32
    ib,keep=_blob(data); eb,ekeep=_blob(AUTH_ENTROPY); out=_DATA_BLOB()
    ok=crypt32.CryptUnprotectData(ctypes.byref(ib),None,ctypes.byref(eb),None,None,0,ctypes.byref(out)); _=keep,ekeep
    if not ok: raise ctypes.WinError()
    try: return ctypes.string_at(out.pbData,out.cbData)
    finally: kernel32.LocalFree(out.pbData)
def load_secret(client_id:str)->bytes:
    reg=json.loads((AUTH_ROOT/"clients.json").read_text(encoding="utf-8")); row=reg["clients"].get(client_id)
    if not isinstance(row,dict) or row.get("status")!="ACTIVE": raise RuntimeError("auditor client inactive")
    perms={str(x) for x in row.get("permissions") or []}
    if perms!={"memory:context"}: raise RuntimeError(f"not least privilege: {sorted(perms)}")
    p=(AUTH_ROOT/str(row["secret_file"])).resolve()
    if AUTH_ROOT.resolve() not in p.parents: raise RuntimeError("secret path escaped auth root")
    secret=dpapi_unprotect(p.read_bytes())
    if len(secret)!=32: raise RuntimeError("invalid secret length")
    return secret
def signed_headers(client_id:str,secret:bytes,method:str,path:str,body:bytes):
    ts=str(int(time.time())); nonce=secrets.token_hex(16); sha=hashlib.sha256(body).hexdigest()
    canonical="\n".join([method.upper(),path,ts,nonce,sha]).encode()
    sig=hmac.new(secret,canonical,hashlib.sha256).hexdigest()
    return {"X-Memory-Client-Id":client_id,"X-Memory-Timestamp":ts,"X-Memory-Nonce":nonce,"X-Memory-Content-SHA256":sha,"X-Memory-Signature":sig}
def request_json(base,client_id,secret,method,path,payload,extra=None,timeout=10):
    base=validate_loopback_service_base_url(base,purpose="retrieval auditor Memory API")
    path=validate_origin_relative_path_query(path,purpose="retrieval auditor Memory API")
    body=b"" if payload is None else json.dumps(payload,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    h=signed_headers(client_id,secret,method,path,body)
    if payload is not None: h["Content-Type"]="application/json"
    if extra: h.update(extra)
    req=urllib.request.Request(base.rstrip("/")+path,data=(body if payload is not None else None),method=method.upper(),headers=h)
    try:
        with open_url_no_redirect(req,timeout=timeout) as r:
            raw=read_http_response_limited(r,max_bytes=MEMORY_API_RESPONSE_MAX_BYTES,purpose="retrieval auditor Memory API")
            return r.status,(json.loads(raw.decode("utf-8")) if raw else {})
    except urllib.error.HTTPError as e:
        raw=read_http_response_limited(e,max_bytes=HTTP_ERROR_RESPONSE_MAX_BYTES,purpose="retrieval auditor Memory API error").decode("utf-8",errors="replace")
        try: data=json.loads(raw) if raw else {}
        except json.JSONDecodeError: data={"raw":raw}
        return e.code,data
def phoenix_health(base:str)->bool:
    try:
        base=validate_loopback_service_base_url(base,purpose="Phoenix")
        req=urllib.request.Request(base+"/healthz",method="GET")
        with open_url_no_redirect(req,timeout=5) as r:
            read_http_response_limited(r,max_bytes=HTTP_ERROR_RESPONSE_MAX_BYTES,purpose="Phoenix health")
            return r.status==200
    except (OSError, ValueError):
        return False
def controlled_path(value: str | Path, root: Path, *, purpose: str, suffix: str | None = None) -> Path:
    path=Path(value).resolve(); boundary=root.resolve()
    if path != boundary and boundary not in path.parents:
        raise ValueError(f"{purpose} path escaped controlled root")
    if suffix is not None and path.suffix.lower() != suffix.lower():
        raise ValueError(f"{purpose} path has invalid suffix")
    return path

def canonical_opa(value: str | Path) -> Path:
    path=Path(value).resolve(); expected=OPA.resolve()
    if path != expected:
        raise ValueError("OPA executable must use the canonical auditor binary")
    return path

def opa_allow(evidence:dict[str,Any],run_dir:Path,opa:Path,policy:Path):
    inp=run_dir/"opa-input.json"; inp.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    cp=subprocess.run([str(opa),"eval","--format=json","--data",str(policy),"--input",str(inp),"data.memory.auditor.allow"],capture_output=True,text=True,timeout=15,env={**os.environ,"PYTHONPATH":""})  # nosec B603 -- opa is canonicalized to the fixed project binary; shell=False.
    if cp.returncode!=0: return False,{"returncode":cp.returncode,"stderr":cp.stderr[-2000:]}
    parsed=json.loads(cp.stdout)
    try: value=bool(parsed["result"][0]["expressions"][0]["value"])
    except (KeyError, IndexError, TypeError): value=False
    return value,parsed
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--baseline",required=True); ap.add_argument("--runs-dir",default=str(RUNS)); ap.add_argument("--opa",default=str(OPA)); ap.add_argument("--policy",default=str(POLICY)); ap.add_argument("--phoenix",default=PHOENIX); args=ap.parse_args()
    bp=controlled_path(args.baseline,BASELINES,purpose="auditor baseline",suffix=".json"); baseline=json.loads(bp.read_text(encoding="utf-8-sig")); rr=controlled_path(args.runs_dir,RUNS,purpose="auditor runs"); rr.mkdir(parents=True,exist_ok=True)
    run_id="rqa-"+datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:10]; rd=rr/run_id; rd.mkdir(parents=True,exist_ok=False)
    client_id=str(baseline["client_id"]); secret=load_secret(client_id); api=validate_loopback_service_base_url(str(baseline["api_base"]),purpose="retrieval auditor Memory API"); namespace=str(baseline["namespace"]); thresholds=dict(baseline["thresholds"]); phoenix_base=validate_loopback_service_base_url(args.phoenix,purpose="Phoenix"); phx_ok=phoenix_health(phoenix_base)
    descriptor=Agent(name="Retrieval Quality Auditor",instructions="Read-only deterministic retrieval quality auditor. Never writes canonical memory, never accesses database directly, never promotes memory scope.")
    tp=register(endpoint=phoenix_base+"/v1/traces",project_name="memoria-permanente-retrieval-quality",batch=False,verbose=False,auto_instrument=False); tracer=tp.get_tracer("memory.retrieval_quality_auditor")
    cases_out=[]; leaks=0; api_failures=0; conflicts_total=0; passes=0; max_latency=0.0
    with tracer.start_as_current_span("retrieval-quality-auditor") as agent_span:
        agent_span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND,OpenInferenceSpanKindValues.AGENT.value); agent_span.set_attribute("memory.auditor.run_id",run_id); agent_span.set_attribute("memory.auditor.client_id",client_id); agent_span.set_attribute("memory.auditor.read_only",True); agent_span.set_attribute("memory.auditor.direct_db",False); agent_span.set_attribute(SpanAttributes.INPUT_VALUE,str(bp))
        for case in baseline["cases"]:
            payload={"query":case["query"],"namespaces":[namespace],"limit":5,**dict(case.get("context") or {})}; headers={str(k):str(v) for k,v in dict(case.get("headers") or {}).items()}; t0=time.perf_counter()
            with tracer.start_as_current_span("retrieval:"+case["name"]) as span:
                span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND,OpenInferenceSpanKindValues.RETRIEVER.value); span.set_attribute(SpanAttributes.INPUT_VALUE,str(case["query"])); span.set_attribute("memory.scope.project",headers.get("X-Memory-Project","")); span.set_attribute("memory.scope.mission",str(payload.get("mission_id") or "")); span.set_attribute("memory.scope.session",str(payload.get("session_id") or ""))
                try: status,data=request_json(api,client_id,secret,"POST","/v1/context/retrieve",payload,headers)
                except (OSError, UnicodeError, ValueError) as exc: status,data=0,{"error":type(exc).__name__,"detail":str(exc)[:500]}
                latency=(time.perf_counter()-t0)*1000.0; max_latency=max(max_latency,latency); selected=data.get("selected",[]) if isinstance(data,dict) else []; keys=[str(x.get("memory_key")) for x in selected if isinstance(x,dict)]; conflicts=data.get("conflicts",[]) if isinstance(data,dict) else []; conflicts_total+=len(conflicts)
                if status!=200: api_failures+=1
                empty=bool(case.get("expected_empty",False)); passed=(status==200 and len(selected)==0) if empty else (status==200 and str(case.get("expected_key")) in keys)
                if empty and status==200 and selected: leaks+=len(selected)
                if passed: passes+=1
                trace_id=data.get("trace_id") if isinstance(data,dict) else None
                row={"name":case["name"],"status":status,"passed":passed,"latency_ms":round(latency,3),"selected_keys":keys,"expected_key":case.get("expected_key"),"expected_empty":empty,"memory_trace_id":trace_id,"retrieval_modes":data.get("retrieval_modes",[]) if isinstance(data,dict) else [],"conflict_count":len(conflicts)}; cases_out.append(row)
                span.set_attribute("memory.retrieval.status",int(status)); span.set_attribute("memory.retrieval.passed",bool(passed)); span.set_attribute("memory.retrieval.selected_count",len(keys)); span.set_attribute("memory.retrieval.trace_id",str(trace_id or "")); span.set_attribute("memory.retrieval.latency_ms",float(latency)); span.set_attribute(SpanAttributes.OUTPUT_VALUE,json.dumps(row,ensure_ascii=False,separators=(",",":")))
        total=max(1,len(cases_out)); pass_rate=passes/total
        evidence={
            "schema_version":1,"run_id":run_id,"baseline_id":baseline.get("baseline_id"),
            "actor":"retrieval-quality-auditor","agent_sdk_descriptor":descriptor.name,
            "client_id":client_id,"operation":"memory:context","read_only":True,"direct_db":False,
            "telemetry":{"phoenix_health":phx_ok,"project":"memoria-permanente-retrieval-quality"},
            "thresholds":thresholds,
            "metrics":{"cases":len(cases_out),"passed":passes,"pass_rate":pass_rate,"scope_leaks":leaks,"api_failures":api_failures,"conflicts":conflicts_total,"max_case_latency_ms":round(max_latency,3)},
            "cases":cases_out,
            "generated_at":datetime.now(UTC).isoformat(),
        }
        opa_path=canonical_opa(args.opa); policy_path=controlled_path(args.policy,POLICY_ROOT,purpose="auditor policy",suffix=".rego"); allowed,opa_result=opa_allow(evidence,rd,opa_path,policy_path)
        evidence["opa"]={"allow":allowed,"policy":str(policy_path)}
        evidence["verdict"]="PASS" if allowed else "FAIL_REGRESSION"
        raw=json.dumps(evidence,ensure_ascii=False,indent=2,sort_keys=True)
        out=rd/"evidence.json"; out.write_text(raw,encoding="utf-8")
        evidence["evidence_sha256"]=hashlib.sha256(out.read_bytes()).hexdigest()
        (rd/"opa-result.json").write_text(json.dumps(opa_result,ensure_ascii=False,indent=2),encoding="utf-8")
        agent_span.set_attribute("memory.auditor.pass_rate",float(pass_rate)); agent_span.set_attribute("memory.auditor.scope_leaks",int(leaks)); agent_span.set_attribute("memory.auditor.api_failures",int(api_failures)); agent_span.set_attribute("memory.auditor.conflicts",int(conflicts_total)); agent_span.set_attribute("memory.auditor.opa_allow",bool(allowed)); agent_span.set_attribute(SpanAttributes.OUTPUT_VALUE,evidence["verdict"])
    try: tp.force_flush(timeout_millis=10000)
    except RuntimeError: pass
    print(json.dumps({"run_id":run_id,"verdict":evidence["verdict"],"pass_rate":pass_rate,"scope_leaks":leaks,"api_failures":api_failures,"conflicts":conflicts_total,"phoenix_health":phx_ok,"evidence":str(out),"evidence_sha256":evidence["evidence_sha256"]},ensure_ascii=False))
    return 0 if allowed else 2
if __name__=="__main__":
    raise SystemExit(main())
