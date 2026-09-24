from __future__ import annotations

import os
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from memory_permanent.canonical_mutation import canonical_mutation_scope  # noqa: E402
from memory_permanent.lifecycle_manager import LifecycleManager  # noqa: E402

PG=Path(r'C:\RMP18\pgsql18\pgsql\bin');HOST='127.0.0.1';PORT='55439';USER='postgres';SRC='memory_recovery';DST='memory_restore_p18'
SRC_DSN=f'postgresql://{USER}@{HOST}:{PORT}/{SRC}';DST_DSN=f'postgresql://{USER}@{HOST}:{PORT}/{DST}'
RUN=datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8];CANARY='P18-CANARY-'+RUN+'-'+uuid.uuid4().hex
PROOF=ROOT/'runtime'/'p18-terminal-proof'/RUN;PROOF.mkdir(parents=True,exist_ok=True)
BID='p18-pre-erasure-'+RUN;PLAIN=PROOF/(BID+'.dump');ENC=PROOF/(BID+'.mpb');MAN=PROOF/(BID+'.encrypted.manifest.json');TMP=PROOF/(BID+'.restore.tmp.dump')
EVID=ROOT/'evidence'/'P18_RECOVERY_TERMINAL_PROOF.json';PD=Path(os.getenv('ProgramData',r'C:\ProgramData'))/'MemoriaPermanente';KEYS=PD/'backup-keys-recovery-proof';LEDGER=PD/'erasure-recovery-proof'
def cmd(args):
 e=os.environ.copy();e.update({'PGHOST':HOST,'PGPORT':PORT,'PGUSER':USER});r=subprocess.run(args,text=True,capture_output=True,env=e)  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.
 if r.returncode: raise RuntimeError((r.stderr or r.stdout)[-2000:])
 return r
def remember(store,key,text,actor):
 with canonical_mutation_scope(actor,'memory.remember'):
  return store.remember(namespace='p18-proof',memory_key=key,content={'proof':'P18','payload':text},content_text=text,provenance={'proof':'P18_RECOVERY_TERMINAL','run':RUN},confidence=1.0,source='recovery-proof',source_version='0.26.1-recovery',tags=['P18','RECOVERY'],changed_by=actor)
def classify(store,item,actor):
 with canonical_mutation_scope(actor,'memory.classify'): out=store.classify([item],'DESCARTAVEL',changed_by=actor)
 if out.get('lifecycle_state')!='DELETE_ELIGIBLE': raise RuntimeError(out)
def present(store):
 p='%'+CANARY+'%'
 with store._connection() as c:
  a=c.execute('SELECT EXISTS(SELECT 1 FROM memory_items WHERE content_text LIKE %s OR content_json::text LIKE %s OR memory_key LIKE %s)',(p,p,p)).fetchone()['exists']
  b=c.execute('SELECT EXISTS(SELECT 1 FROM memory_versions WHERE content_text LIKE %s OR content_json::text LIKE %s)',(p,p)).fetchone()['exists']
 return bool(a or b)
def state(store,item):
 with store._connection() as c:
  r=c.execute('SELECT memory_key,content_text,content_json,content_sha256,source,source_version FROM memory_items WHERE item_id=%s',(item,)).fetchone();return dict(r) if r else {}
def roundtrip(store):
 item=remember(store,'p18-roundtrip-'+RUN,'ROUNDTRIP-'+RUN,'p18-requester');classify(store,item,'p18-requester');lm=LifecycleManager(store)
 with canonical_mutation_scope('p18-requester','lifecycle.request_purge'): req=lm.request_purge(item_id=item,reason='P18 M12 roundtrip proof',recovery_window_seconds=300,evidence={'run':RUN},actor='p18-requester')
 rid=str(req['request_id'])
 with canonical_mutation_scope('p18-requester','lifecycle.quarantine'): lm.quarantine(request_id=rid,evidence={'run':RUN},actor='p18-requester')
 with canonical_mutation_scope('p18-approver','lifecycle.approve'): lm.approve(request_id=rid,evidence={'run':RUN},actor='p18-approver')
 with canonical_mutation_scope('p18-approver','lifecycle.purge'): lm.purge(request_id=rid,evidence={'run':RUN},actor='p18-approver')
 with canonical_mutation_scope('p18-recovery','lifecycle.recover'): rec=lm.recover(request_id=rid,evidence={'run':RUN},actor='p18-recovery')
 return {'item_id':item,'request_id':rid,'roundtrip_proof_id':rec['roundtrip_proof_id']}
def finalize(store,item):
 lm=LifecycleManager(store);classify(store,item,'p18-requester')
 with canonical_mutation_scope('p18-requester','lifecycle.request_purge'): req=lm.request_purge(item_id=item,reason='P18 legal erasure proof',recovery_window_seconds=0,evidence={'run':RUN},actor='p18-requester')
 rid=str(req['request_id'])
 with canonical_mutation_scope('p18-requester','lifecycle.quarantine'): lm.quarantine(request_id=rid,evidence={'run':RUN},actor='p18-requester')
 with canonical_mutation_scope('p18-approver','lifecycle.approve'): lm.approve(request_id=rid,evidence={'run':RUN},actor='p18-approver')
 with canonical_mutation_scope('p18-approver','lifecycle.purge'): lm.purge(request_id=rid,evidence={'run':RUN},actor='p18-approver')
 with canonical_mutation_scope('p18-approver','lifecycle.finalize'): fin=lm.finalize(request_id=rid,evidence={'run':RUN},actor='p18-approver')
 return {'request_id':rid,'irreversibility_proof_id':fin['irreversibility_proof_id']}
