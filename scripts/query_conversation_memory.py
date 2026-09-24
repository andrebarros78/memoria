from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API='http://127.0.0.1:8787'
ref=sys.argv[1]
cid=ref.split('/c/')[-1] if '/c/' in ref else ref

def get(path):
    with urllib.request.urlopen(API+path,timeout=5) as r:  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
        return json.loads(r.read().decode('utf-8'))

result={'conversation_id':cid,'external_ref':ref}
try:
    q=urllib.parse.urlencode({'provider':'chatgpt','external_session_ref':ref})
    resolved=get('/v1/external-sessions/resolve?'+q)
    if not resolved.get('found') and ref != cid:
        q=urllib.parse.urlencode({'provider':'chatgpt','external_session_ref':cid})
        resolved=get('/v1/external-sessions/resolve?'+q)
    result['resolved']=resolved
    result['continuation_payload']=resolved.get('continuation_payload')
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
except urllib.error.HTTPError as e:
    result['http_error']=e.code
    try: result['detail']=e.read().decode('utf-8','replace')
    except OSError: pass
    print(json.dumps(result,ensure_ascii=False,indent=2))
