from __future__ import annotations

import hashlib
import json
from datetime import UTC
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from memory_permanent.store import canonical

ROOT=Path(r'C:\New Projet\MEMORIA-PERMANENTE')
raw=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip(); h,p,d,u,pw=raw.split(':',4)
dsn=f'host={h} port={p} dbname={d} user={u} password={pw} connect_timeout=5'
with psycopg.connect(dsn,row_factory=dict_row) as conn:
    conn.execute("select set_config('app.current_tenant','__SYSTEM__',true)")
    rows=conn.execute('select seq,event_type,payload,previous_hash,event_hash,created_at from audit_events order by seq').fetchall()
seen={'0'*64}; invalid_hash=[]; missing_parent=[]; forks={}
for r in rows:
    ts=r['created_at'].astimezone(UTC).isoformat()
    own=hashlib.sha256((str(r['previous_hash'])+canonical(r['payload'])+r['event_type']+ts).encode()).hexdigest()
    if own!=str(r['event_hash']): invalid_hash.append(int(r['seq']))
    if str(r['previous_hash']) not in seen: missing_parent.append(int(r['seq']))
    forks.setdefault(str(r['previous_hash']),[]).append(int(r['seq']))
    seen.add(str(r['event_hash']))
fork_groups=[v for k,v in forks.items() if k!='0'*64 and len(v)>1]
manifest=hashlib.sha256('\n'.join(f"{int(r['seq'])}:{r['previous_hash']}:{r['event_hash']}" for r in rows).encode()).hexdigest()
print(json.dumps({'events':len(rows),'invalid_hash':invalid_hash,'missing_parent':missing_parent,'fork_group_count':len(fork_groups),'fork_event_count':sum(len(x) for x in fork_groups),'fork_groups':fork_groups[:30],'manifest_root':manifest,'PASS':not invalid_hash and not missing_parent},indent=2))
