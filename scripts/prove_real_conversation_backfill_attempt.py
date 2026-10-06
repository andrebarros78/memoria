from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(r'C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0'); sys.path.insert(0,str(ROOT/'integration'))
from chatgpt_invisible_capture import capture_chatgpt_conversation  # noqa: E402


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--conversation-ref',required=True)
    args=ap.parse_args()
    REF=args.conversation_ref.strip()
    CID=REF.rstrip('/').split('/')[-1]
    result=capture_chatgpt_conversation(REF,memory_api='http://127.0.0.1:8787',learning_project_id='mem-v4-chatgpt-recovery-'+CID[:8],browser_session_id='mem-v4-chatgpt-recovery-'+CID[:8])
    url='http://127.0.0.1:8787/v1/external-sessions/resolve?provider=chatgpt&external_session_ref='+urllib.parse.quote(CID)
    start=time.perf_counter()
    with urllib.request.urlopen(url,timeout=5) as r: resolved=json.loads(r.read().decode())  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
    lookup_ms=(time.perf_counter()-start)*1000
    classification='BLOCKED_EXTERNAL_SOURCE_403' if result.get('status')=='EXTERNAL_SOURCE_BLOCKED_403' else result.get('status')
    proof={
      'generated_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),
      'target':{'external_ref':REF,'conversation_id':CID},
      'bridge_result':result,
      'resolver_after_attempt':{'found':resolved.get('found'),'reason':resolved.get('reason'),'recoverable':resolved.get('recoverable'),'lookup_ms':round(lookup_ms,3)},
      'classification':classification,
      'operator_desktop_used':result.get('operator_desktop_used'),
      'personal_browser_used':result.get('personal_browser_used'),
      'REAL_CONVERSATION_RECOVERY_PROVEN':bool(resolved.get('found') and resolved.get('recoverable')),
    }
    safe=CID.replace('/','_')
    ev=ROOT/'evidence'/f'REAL_CONVERSATION_BACKFILL_{safe}.json'
    ev.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    sha=hashlib.sha256(ev.read_bytes()).hexdigest().upper()
    print(json.dumps({'status':classification,'http_status':result.get('http_status'),'message_count':result.get('message_count'),'operator_desktop_used':result.get('operator_desktop_used'),'personal_browser_used':result.get('personal_browser_used'),'resolver_found':resolved.get('found'),'resolver_reason':resolved.get('reason'),'recoverable':resolved.get('recoverable'),'lookup_ms':round(lookup_ms,3),'evidence':str(ev),'evidence_sha256':sha},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
