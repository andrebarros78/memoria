from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from memory_permanent.client_auth import (
    CLIENT_AUTH_ENTROPY,
    auth_root,
    canonical_request,
    validate_client_id,
)
from memory_permanent.network_policy import (
    HTTP_ERROR_RESPONSE_MAX_BYTES,
    MEMORY_API_RESPONSE_MAX_BYTES,
    open_url_no_redirect,
    read_http_response_limited,
)
from memory_permanent.secret_sanitizer import (
    WindowsDpapiKeyProvider,
    platform_protected_key_path,
)
from memory_permanent.signed_client import SignedMemoryClient

BASE=os.getenv('MEMORY_API_BASE','http://127.0.0.1:8790').rstrip('/')
ROOT=Path(os.getenv('MEMORY_PROJECT_ROOT',Path(__file__).resolve().parents[1])).resolve()
EVID=ROOT/'evidence'/'SECURITY_AUTH_HARDENING_LIVE_PROOF.json'
EVID_MD=ROOT/'evidence'/'SECURITY_AUTH_HARDENING_LIVE_PROOF.md'

def raw(method,path,headers=None,body=None):
    req=urllib.request.Request(BASE+path,data=body,method=method,headers=headers or {})
    try:
        with open_url_no_redirect(req,timeout=15) as r:
            data=read_http_response_limited(r,max_bytes=MEMORY_API_RESPONSE_MAX_BYTES,purpose='security auth proof').decode('utf-8',errors='replace')
            try: obj=json.loads(data) if data else {}
            except json.JSONDecodeError: obj=data
            return r.status,obj
    except urllib.error.HTTPError as e:
        data=read_http_response_limited(e,max_bytes=HTTP_ERROR_RESPONSE_MAX_BYTES,purpose='security auth proof error').decode('utf-8',errors='replace')
        try: obj=json.loads(data) if data else {}
        except json.JSONDecodeError: obj=data
        return e.code,obj

def secret(client):
    client = validate_client_id(client)
    key_path = platform_protected_key_path(auth_root() / 'clients', client)
    return WindowsDpapiKeyProvider(key_path,machine_scope=True,entropy=CLIENT_AUTH_ENTROPY).load_or_create()

def check(name,actual,expected,detail=None):
    ok=actual==expected
    checks.append({'name':name,'actual':actual,'expected':expected,'pass':ok,'detail':detail})
    return ok

checks=[]
# Public path remains available.
s,b=raw('GET','/health'); check('public_health',s,200, b.get('version') if isinstance(b,dict) else None)

# Unsigned access and spoofed declarative identity must fail closed.
s,b=raw('GET','/v1/memories?limit=1'); check('unsigned_general_rejected',s,401)
s,b=raw('GET','/v1/memories?limit=1',{'X-Memory-Tenant':'TENANT_ATTACKER','X-Memory-Project':'project-attack'}); check('unsigned_identity_spoof_rejected',s,401)

admin=SignedMemoryClient(BASE,'local-admin')
capture=SignedMemoryClient(BASE,'chatgpt-capture')
# Valid admin signed call.
s,b=admin.request('GET','/v1/dashboard/summary',extra_headers={'X-Memory-Tenant':'LEGACY'}); check('signed_admin_allowed',s,200)

# Tampered signature.
path='/v1/memories?limit=1'; h=admin.headers('GET',path,b'',{'X-Memory-Tenant':'LEGACY'}); sig=h['X-Memory-Signature']; h['X-Memory-Signature']=('0' if sig[0]!='0' else '1')+sig[1:]
s,b=raw('GET',path,h); check('tampered_signature_rejected',s,401)

# Signed body hash does not match transmitted body.
path='/v1/memories'; good=b'{"invalid":"signed-body"}'; bad=b'{"invalid":"tampered-body"}'
h=admin.headers('POST',path,good,{'X-Memory-Tenant':'LEGACY','Content-Type':'application/json'})
s,b=raw('POST',path,h,bad); check('tampered_body_rejected',s,401)

# Replay exact same signed request.
path='/v1/memories?limit=1'; h=admin.headers('GET',path,b'',{'X-Memory-Tenant':'LEGACY'})
s1,b1=raw('GET',path,h); s2,b2=raw('GET',path,h)
check('replay_first_request_allowed',s1,200); check('replay_second_request_rejected',s2,401)

# Restricted capture client: tenant spoof must fail after valid authentication.
payload={'provider':'chatgpt','external_session_ref':'security-auth-proof-'+str(int(time.time())),'objective':'Security authentication proof','role':'user','text':'SECURITY_AUTH_PROOF_EVENT','message_id':'proof-1','ordinal':0,'project_id':None,'capture_source':'SECURITY_TEST','process_now':False}
s,b=capture.request('POST','/v1/conversation-ingestion/turn',payload,extra_headers={'X-Memory-Tenant':'LEGACY'}); check('capture_client_ingest_allowed',s,201)
s,b=capture.request('GET','/v1/dashboard/summary',extra_headers={'X-Memory-Tenant':'LEGACY'}); check('capture_client_admin_denied',s,403)
s,b=capture.request('POST','/v1/conversation-ingestion/turn',payload,extra_headers={'X-Memory-Tenant':'TENANT_ATTACKER'}); check('capture_client_tenant_spoof_denied',s,403)

# Stale timestamp with otherwise valid HMAC.
path='/v1/memories?limit=1'; sec=secret('local-admin'); ts=str(int(time.time())-1000); nonce='a'*32; bodyhash=hashlib.sha256(b'').hexdigest()
sig=hmac.new(sec,canonical_request('GET',path,ts,nonce,bodyhash),hashlib.sha256).hexdigest()
h={'X-Memory-Client-Id':'local-admin','X-Memory-Timestamp':ts,'X-Memory-Nonce':nonce,'X-Memory-Content-SHA256':bodyhash,'X-Memory-Signature':sig,'X-Memory-Tenant':'LEGACY'}
s,b=raw('GET',path,h); check('stale_timestamp_rejected',s,401)

failed=[c for c in checks if not c['pass']]
proof={'gate':'SECURITY_AUTH_HARDENING','result':'PASS' if not failed else 'FAIL','auth_scheme':'MEMORY-HMAC-SHA256-V1','api_version':'0.10.1','checks':checks,'failed_checks':[c['name'] for c in failed],'secrets_exposed':False,'generated_at_epoch':int(time.time())}
EVID.write_text(json.dumps(proof,indent=2,ensure_ascii=False),encoding='utf-8')
lines=['# SECURITY AUTH HARDENING LIVE PROOF','',f"Result: **{proof['result']}**",'',f"Auth scheme: `{proof['auth_scheme']}`",'', '| Check | Actual | Expected | Result |','|---|---:|---:|---|']
for c in checks: lines.append(f"| {c['name']} | {c['actual']} | {c['expected']} | {'PASS' if c['pass'] else 'FAIL'} |")
EVID_MD.write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({'result':proof['result'],'passed':len(checks)-len(failed),'total':len(checks),'failed':proof['failed_checks'],'evidence':str(EVID)},ensure_ascii=False))
raise SystemExit(0 if not failed else 1)

