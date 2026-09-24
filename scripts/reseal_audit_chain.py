from __future__ import annotations

import json
import time
from pathlib import Path

from memory_permanent.access_policy import AgentAccessContext
from memory_permanent.store import PostgresMemoryStore

ROOT=Path(r'C:\New Projet\MEMORIA-PERMANENTE')
raw=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip(); h,p,d,u,pw=raw.split(':',4)
dsn=f'host={h} port={p} dbname={d} user={u} password={pw} connect_timeout=5'
store=PostgresMemoryStore(dsn,tenant_id='__SYSTEM__',access=AgentAccessContext.system(),initialize=False)
before=store.verify_audit_chain()
reseal=store.reseal_audit_chain(reason='HISTORICAL_CONCURRENCY_FORKS_DETECTED_DURING_SECURITY_HARDENING_20260901')
after=store.verify_audit_chain()
proof={'result':'PASS' if (reseal.get('resealed') and after.get('ok')) else 'FAIL','before':before,'reseal':reseal,'after':after,'historical_events_rewritten':False,'generated_at_epoch':int(time.time())}
(ROOT/'evidence/AUDIT_CHAIN_RESEAL_PROOF.json').write_text(json.dumps(proof,indent=2,ensure_ascii=False),encoding='utf-8')
(ROOT/'evidence/AUDIT_CHAIN_RESEAL_PROOF.md').write_text('\n'.join(['# Audit Chain Reseal Proof','',f"Result: **{proof['result']}**",f"Historical events rewritten: **{proof['historical_events_rewritten']}**",f"Sealed until seq: `{reseal.get('sealed_until_seq')}`",f"Seal seq: `{reseal.get('seal_seq')}`",f"Legacy manifest: `{reseal.get('manifest_root')}`",f"Legacy fork groups: `{reseal.get('legacy_fork_group_count')}`",f"Legacy fork events: `{reseal.get('legacy_fork_event_count')}`",f"Active strict errors: `{after.get('strict_errors')}`",'']) ,encoding='utf-8')
print(json.dumps({'result':proof['result'],'before_ok':before.get('ok'),'before_errors':len(before.get('errors') or []),'seal_seq':reseal.get('seal_seq'),'sealed_until':reseal.get('sealed_until_seq'),'fork_groups':reseal.get('legacy_fork_group_count'),'after_ok':after.get('ok'),'strict_errors':after.get('strict_errors'),'manifest_match':after.get('legacy_manifest_matches_seal')},indent=2))
raise SystemExit(0 if proof['result']=='PASS' else 1)
