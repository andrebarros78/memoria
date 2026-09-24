import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from memory_permanent.canonical_mutation import canonical_mutation_scope  # noqa: E402
from memory_permanent.lifecycle_manager import LifecycleManager  # noqa: E402
from memory_permanent.store import PostgresMemoryStore  # noqa: E402

DSN='postgresql://postgres@127.0.0.1:55439/memory_recovery';run=datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8];store=PostgresMemoryStore(DSN,tenant_id='LEGACY')
def rem(k,t,a):
 with canonical_mutation_scope(a,'memory.remember'):
  return store.remember(namespace='p18-proof',memory_key=k,content={'proof':'P18','payload':t},content_text=t,provenance={'proof':'P18_RECOVERY_TERMINAL','run':run},confidence=1.0,source='recovery-proof',source_version='0.26.1-recovery',tags=['P18','RECOVERY'],changed_by=a)
def cls(i,a):
 with canonical_mutation_scope(a,'memory.classify'): store.classify([i],'DESCARTAVEL',changed_by=a)
lm=LifecycleManager(store);rt=rem('p18-roundtrip-'+run,'ROUNDTRIP-'+run,'p18-requester');cls(rt,'p18-requester')
with canonical_mutation_scope('p18-requester','lifecycle.request_purge'): q=lm.request_purge(item_id=rt,reason='P18 M12 roundtrip proof',recovery_window_seconds=300,evidence={'run':run},actor='p18-requester')
rid=str(q['request_id'])
with canonical_mutation_scope('p18-requester','lifecycle.quarantine'): lm.quarantine(request_id=rid,evidence={'run':run},actor='p18-requester')
with canonical_mutation_scope('p18-approver','lifecycle.approve'): lm.approve(request_id=rid,evidence={'run':run},actor='p18-approver')
with canonical_mutation_scope('p18-approver','lifecycle.purge'): lm.purge(request_id=rid,evidence={'run':run},actor='p18-approver')
with canonical_mutation_scope('p18-recovery','lifecycle.recover'): rec=lm.recover(request_id=rid,evidence={'run':run},actor='p18-recovery')
canary='P18-CANARY-'+run+'-'+uuid.uuid4().hex;item=rem('p18-canary-'+run,canary,'p18-requester')
out={'run':run,'roundtrip_item':rt,'roundtrip_request':rid,'roundtrip_proof':rec['roundtrip_proof_id'],'canary':canary,'canary_item':item,'migration_count':len(store.migrations())}
(ROOT/'runtime').mkdir(exist_ok=True);(ROOT/'runtime'/'p18-stage.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in out.items() if k!='canary'},ensure_ascii=False))
