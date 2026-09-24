import json
from pathlib import Path

import psycopg

ROOT=Path(r'C:\New Projet\MEMORIA-PERMANENTE')
h,p,d,u,pw=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip().split(':',4)
with psycopg.connect(f'host={h} port={p} dbname={d} user={u} password={pw}') as c:
    c.execute("select set_config('app.current_tenant','__SYSTEM__',true)")
    categories=[x[0] for x in c.execute('select distinct category from memory_items order by 1').fetchall()]
    scopes=[x[0] for x in c.execute('select distinct sharing_scope from memory_items order by 1').fetchall()]
print(json.dumps({'categories':categories,'scopes':scopes},ensure_ascii=False,indent=2))
