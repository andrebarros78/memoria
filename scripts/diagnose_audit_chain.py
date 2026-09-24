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
    rows=conn.execute('select seq,event_type,target_id,payload,previous_hash,event_hash,created_at from audit_events order by seq').fetchall()
prev='0'*64; issues=[]
for r in rows:
    ts=r['created_at'].astimezone(UTC).isoformat()
    expected=hashlib.sha256((prev+canonical(r['payload'])+r['event_type']+ts).encode()).hexdigest()
    pm=str(r['previous_hash'])==prev; hm=str(r['event_hash'])==expected
    if not(pm and hm):
        issues.append({'seq':int(r['seq']),'event_type':r['event_type'],'previous_match':pm,'hash_match':hm,'stored_prev_prefix':str(r['previous_hash'])[:12],'expected_prev_prefix':prev[:12],'stored_hash_prefix':str(r['event_hash'])[:12],'expected_hash_prefix':expected[:12],'created_at':ts})
    prev=str(r['event_hash'])
print(json.dumps({'events':len(rows),'issue_count':len(issues),'first_issues':issues[:30]},indent=2))
