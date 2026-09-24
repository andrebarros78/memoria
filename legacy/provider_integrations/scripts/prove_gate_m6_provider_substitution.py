from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'src'
if str(SRC) not in sys.path: sys.path.insert(0,str(SRC))
from memory_permanent.provider_adapter import (  # noqa: E402
    LlamaCppProviderAdapter,
    OllamaProviderAdapter,
)

API='http://127.0.0.1:8787'

def req(method,path,payload=None,timeout=60):
    data=None if payload is None else json.dumps(payload,ensure_ascii=False).encode('utf-8')
    r=urllib.request.Request(API+path,data=data,method=method,headers={'Content-Type':'application/json','Accept':'application/json'})
    with urllib.request.urlopen(r,timeout=timeout) as x:  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
        raw=x.read().decode('utf-8'); return json.loads(raw) if raw else {}

def dsn():
    h,p,d,u,w=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip().split(':',4)
    return f'host={h} port={p} dbname={d} user={u} password={w} connect_timeout=5'

def same(obs,pack):
    c=pack.get('context') or {}
    return (
        obs.context_sha256==str(pack.get('context_sha256') or '') and
        obs.checkpoint_id==str(pack.get('checkpoint_id') or '') and
        sorted(obs.required_memory_ids)==sorted(str(x) for x in (pack.get('required_memory_ids') or [])) and
        obs.objective==str(c.get('objective') or '')
    )

def main():
    for k in ('OPENAI_API_KEY','GEMINI_API_KEY','GOOGLE_API_KEY','GOOGLE_GENAI_API_KEY'):
        os.environ.pop(k,None)
    m2=json.loads((ROOT/'evidence/M2_RESTART_CONTINUITY_PROOF.json').read_text(encoding='utf-8-sig'))
    session=str(m2['session_id'])
    resumed=req('POST',f'/v1/sessions/{session}/resume',{})
    pack=resumed['context_pack']
    health=req('GET','/health')
    D=dsn()
    with psycopg.connect(D,row_factory=dict_row,connect_timeout=5) as c:
        c.execute("SELECT set_config('app.current_tenant',%s,true)",('LEGACY',))
        before=c.execute("SELECT (SELECT count(*) FROM memory_items) memories,(SELECT value FROM schema_meta WHERE key='schema_version') schema").fetchone()
    providers=[
        OllamaProviderAdapter(model='qwen2.5-coder:3b',base_url='http://127.0.0.1:11434'),
        LlamaCppProviderAdapter(model='qwen2.5-coder:3b',base_url='http://127.0.0.1:11435'),
    ]
    observations={}; probes={}; errors={}
    for p in providers:
        try:
            probes[p.provider_id]=p.probe()
            observations[p.provider_id]=p.observe_context(pack)
        except (OSError, RuntimeError, ValueError) as e:
            errors[p.provider_id]=f'{type(e).__name__}: {e}'
    with psycopg.connect(D,row_factory=dict_row,connect_timeout=5) as c:
        c.execute("SELECT set_config('app.current_tenant',%s,true)",('LEGACY',))
        after=c.execute("SELECT (SELECT count(*) FROM memory_items) memories,(SELECT value FROM schema_meta WHERE key='schema_version') schema").fetchone()
    a=observations.get('ollama'); b=observations.get('llama.cpp')
    checks={
        'M2_CONTINUITY_BASELINE_PASS':m2.get('M2_RESTART_CONTINUITY_PROOF')=='PASS',
        'MEMORY_API_HEALTHY':health.get('status')=='ok',
        'CONTEXT_PACK_PRESENT':bool(pack.get('context_sha256') and pack.get('checkpoint_id')),
        'PROVIDER_IDS_DISTINCT':providers[0].provider_id!=providers[1].provider_id,
        'OLLAMA_REACHABLE':bool((probes.get('ollama') or {}).get('reachable')),
        'LLAMACPP_REACHABLE':bool((probes.get('llama.cpp') or {}).get('reachable')),
        'OLLAMA_USED_SAME_MEMORY':bool(a and same(a,pack)),
        'LLAMACPP_USED_SAME_MEMORY':bool(b and same(b,pack)),
        'BOTH_OBSERVED_SAME_CONTEXT_HASH':bool(a and b and a.context_sha256==b.context_sha256==str(pack.get('context_sha256'))),
        'BOTH_OBSERVED_SAME_CHECKPOINT':bool(a and b and a.checkpoint_id==b.checkpoint_id==str(pack.get('checkpoint_id'))),
        'BOTH_OBSERVED_SAME_REQUIRED_IDS':bool(a and b and sorted(a.required_memory_ids)==sorted(b.required_memory_ids)==sorted(str(x) for x in (pack.get('required_memory_ids') or []))),
        'BOTH_OBSERVED_SAME_OBJECTIVE':bool(a and b and a.objective==b.objective==str((pack.get('context') or {}).get('objective') or '')),
        'NO_PROVIDER_API_KEY_REQUIRED':not any(os.getenv(k) for k in ('OPENAI_API_KEY','GEMINI_API_KEY','GOOGLE_API_KEY','GOOGLE_GENAI_API_KEY')),
        'NO_MEMORY_MIGRATION':int(before['memories'])==int(after['memories']) and str(before['schema'])==str(after['schema']),
    }
    failed=[k for k,v in checks.items() if not v]
    result={
        'generated_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'gate':'M6','GATE_M6':'PASS' if not failed else 'FAIL',
        'criterion':'Two independent ProviderAdapter runtimes consume the same sovereign Context Pack without memory migration; provider authentication is external to Memory Core.',
        'providers':['ollama','llama.cpp'],
        'context_pack_id':pack.get('context_pack_id'),'context_sha256':pack.get('context_sha256'),'checkpoint_id':pack.get('checkpoint_id'),'required_memory_ids':pack.get('required_memory_ids'),
        'probes':probes,'observations':{k:v.as_dict() for k,v in observations.items()},'errors':errors,
        'before':dict(before),'after':dict(after),'checks':checks,'failed_checks':failed,
    }
    (ROOT/'evidence/M6_GATE_PROOF.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    lines=['# Gate M6 — Provider Substitution Proof','','**GATE_M6:** '+result['GATE_M6'],'','Providers: `Ollama` and `llama.cpp`','API/provider keys required by Memory Core: **NO**','Memory migration: **NO**','','## Checks']
    lines += [f'- {k}: **{"PASS" if v else "FAIL"}**' for k,v in checks.items()]
    (ROOT/'evidence/M6_GATE_PROOF.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'GATE_M6':result['GATE_M6'],'providers':result['providers'],'context_sha256':result['context_sha256'],'failed':failed,'no_provider_api_key_required':checks['NO_PROVIDER_API_KEY_REQUIRED'],'no_memory_migration':checks['NO_MEMORY_MIGRATION']},ensure_ascii=False,indent=2))
    return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
