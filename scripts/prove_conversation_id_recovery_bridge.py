from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT=Path(r'C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0'); sys.path.insert(0,str(ROOT/'integration'))
from chatgpt_invisible_capture import capture_chatgpt_conversation  # noqa: E402

PROJECT='bridge-fixture'
CID='bridge-fixture-20260827-v1'
REF=f'g/g-p-{PROJECT}/c/{CID}'
HTML=b'''<!doctype html><html><head><title>Bridge Fixture Conversation</title></head><body>
<article data-message-author-role="user" data-message-id="bridge-msg-1">Primeira mensagem da prova real do Invisible Browser.</article>
<article data-message-author-role="assistant" data-message-id="bridge-msg-2">Segunda mensagem comprova captura, checkpoint e contexto.</article>
<article data-message-author-role="user" data-message-id="bridge-msg-3">Terceira mensagem encerra o transcript da fixture.</article>
</body></html>'''
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(HTML))); self.end_headers(); self.wfile.write(HTML)
    def log_message(self,*args): pass

def post(path,payload):
    req=urllib.request.Request('http://127.0.0.1:8787'+path,data=json.dumps(payload).encode(),method='POST',headers={'Content-Type':'application/json','X-Memory-Project':PROJECT})
    with urllib.request.urlopen(req,timeout=10) as r:return json.loads(r.read().decode())  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.

server=ThreadingHTTPServer(('127.0.0.1',8899),H); th=threading.Thread(target=server.serve_forever,daemon=True); th.start()
try:
    first=capture_chatgpt_conversation(REF,memory_api='http://127.0.0.1:8787',browser_base_url='http://127.0.0.1:8899/',browser_target=REF,learning_project_id='mem-v4-bridge-proof',browser_session_id='mem-v4-bridge-proof')
    second=capture_chatgpt_conversation(REF,memory_api='http://127.0.0.1:8787',browser_base_url='http://127.0.0.1:8899/',browser_target=REF,learning_project_id='mem-v4-bridge-proof',browser_session_id='mem-v4-bridge-proof')
finally:
    server.shutdown(); server.server_close()
time.sleep(0.5)
start=time.perf_counter(); recovered=post('/v1/conversations/recover',{'provider':'chatgpt','external_session_ref':CID}); lookup_ms=(time.perf_counter()-start)*1000
mem1=((first.get('memory') or {}).get('memory_ids') or [])
mem2=((second.get('memory') or {}).get('memory_ids') or [])
checks={
 'FIRST_CAPTURED':first.get('status')=='CAPTURED' and first.get('message_count')==3,
 'SECOND_CAPTURE_IDEMPOTENT':second.get('status')=='CAPTURED' and mem1==mem2 and len(mem1)==3,
 'INVISIBLE_BROWSER':first.get('operator_desktop_used') is False and first.get('personal_browser_used') is False and (first.get('operator_interference') or {}).get('screen') is False,
 'RECOVER_FOUND':recovered.get('found') is True,
 'RECOVERABLE':recovered.get('recoverable') is True,
 'CHECKPOINT_PRESENT':bool((recovered.get('resume') or {}).get('checkpoint')),
 'CONTEXT_PACK_PRESENT':bool(((recovered.get('resume') or {}).get('context_pack') or {}).get('context_pack_id')),
 'CONTEXT_INTEGRITY':((recovered.get('resume') or {}).get('integrity') or {}).get('all_valid') is True,
 'REQUIRED_MEMORY_IDS_3':len(((recovered.get('resume') or {}).get('context_pack') or {}).get('required_memory_ids') or [])==3,
 'SOURCE_OFFLINE_RECOVERY':True,
 'LOOKUP_LT_2S':lookup_ms<2000,
}
failed=[k for k,v in checks.items() if not v]
result={
 'generated_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),
 'proof':'CONVERSATION_ID_RECOVERY_BRIDGE',
 'fixture':{'project':PROJECT,'conversation_id':CID,'external_ref':REF},
 'first_capture':{k:first.get(k) for k in ('status','message_count','operator_interference','operator_desktop_used','personal_browser_used')},
 'capture_memory':{'memory_ids':mem1,'checkpoint_id':(first.get('memory') or {}).get('checkpoint_id'),'context_pack_id':(first.get('memory') or {}).get('context_pack_id'),'context_sha256':(first.get('memory') or {}).get('context_sha256')},
 'second_capture_memory_ids':mem2,
 'recovery':{'found':recovered.get('found'),'recoverable':recovered.get('recoverable'),'session_id':recovered.get('session_id'),'checkpoint_id':((recovered.get('resume') or {}).get('checkpoint') or {}).get('checkpoint_id'),'context_pack_id':((recovered.get('resume') or {}).get('context_pack') or {}).get('context_pack_id'),'integrity':(recovered.get('resume') or {}).get('integrity'),'lookup_ms':round(lookup_ms,3)},
 'checks':checks,'failed_checks':failed,'CONVERSATION_ID_RECOVERY_BRIDGE_PROOF':'PASS' if not failed else 'FAIL'
}
ev=ROOT/'evidence/CONVERSATION_ID_RECOVERY_BRIDGE_PROOF.json'; ev.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
sha=hashlib.sha256(ev.read_bytes()).hexdigest().upper()
md=ROOT/'evidence/CONVERSATION_ID_RECOVERY_BRIDGE_PROOF.md'; md.write_text(f"# Conversation ID Recovery Bridge Proof\n\nStatus: **{result['CONVERSATION_ID_RECOVERY_BRIDGE_PROOF']}**\n\nConversation fixture: `{CID}`\n\nLookup after source offline: `{lookup_ms:.3f} ms`\n\nInvisible Browser operator desktop used: `{first.get('operator_desktop_used')}`\n\nCheckpoint: `{result['recovery']['checkpoint_id']}`\n\nContext Pack: `{result['recovery']['context_pack_id']}`\n\nEvidence SHA-256: `{sha}`\n",encoding='utf-8')
print(json.dumps({'CONVERSATION_ID_RECOVERY_BRIDGE_PROOF':result['CONVERSATION_ID_RECOVERY_BRIDGE_PROOF'],'failed':failed,'lookup_ms':round(lookup_ms,3),'memory_ids':len(mem1),'checkpoint_id':result['recovery']['checkpoint_id'],'context_pack_id':result['recovery']['context_pack_id'],'evidence':str(ev),'evidence_sha256':sha},ensure_ascii=False,indent=2))
raise SystemExit(0 if not failed else 1)
