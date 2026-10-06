from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from memory_permanent.signed_client import SignedMemoryClient

ROOT=Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0")
c=SignedMemoryClient("http://127.0.0.1:8787","governor-runtime")
suffix=uuid.uuid4().hex[:12]
checks={}
status,body=c.request("GET","/v1/memories?limit=1")
checks["READ_ALLOWED"] = status==200 and isinstance(body,dict)
status,ctx=c.request("POST","/v1/context/retrieve",{"query":"memory continuity","namespaces":["COMMON","WINDOWS"],"limit":2})
checks["CONTEXT_ALLOWED"] = status==200 and isinstance(ctx,dict) and bool(ctx.get("trace_id"))
payload={"namespace":"M10_HMAC","memory_key":"governor-hmac-"+suffix,"category":"EVIDENCE","content":{"proof":"governor-runtime-hmac","suffix":suffix},"content_text":"Governor runtime HMAC least privilege integration proof "+suffix,"provenance":{"trusted":True,"proof":"M10_HMAC"},"confidence":1.0,"source":"governor-windows","source_version":"M10-HMAC","tags":["M10","HMAC"],"changed_by":"governor-runtime"}
status,created=c.request("POST","/v1/memories",payload)
checks["WRITE_ALLOWED"] = status==201 and str(created.get("item_id","")).startswith("mem-")
status,_=c.request("GET","/v1/dashboard/summary")
checks["ADMIN_DASHBOARD_DENIED"] = status==403
status,_=c.request("POST","/v1/memories/classify",{"item_ids":[created.get("item_id","mem-none")],"operator_class":"ATIVA","changed_by":"governor-runtime"})
checks["ADMIN_CLASSIFY_DENIED"] = status==403
status,_=c.request("POST","/v1/purge",{})
checks["PURGE_DENIED"] = status==403
failed=[k for k,v in checks.items() if not v]
result={"generated_at":time.strftime('%Y-%m-%dT%H:%M:%S'),"client_id":"governor-runtime","permissions_expected":["memory:read","memory:write","memory:context"],"created_item_id":created.get("item_id") if isinstance(created,dict) else None,"checks":checks,"failed_checks":failed,"PASS":not failed}
(ROOT/'evidence/GOVERNOR_HMAC_PERMISSION_PROOF.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
raise SystemExit(0 if not failed else 1)
