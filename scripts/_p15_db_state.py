from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT=Path(r"C:\New Projet\MEMORIA-PERMANENTE")
h,p,d,u,pw=(ROOT/"runtime/secrets/pgpass.conf").read_text(encoding="ascii").strip().split(":",4)
with psycopg.connect(f"host={h} port={p} dbname={d} user={u} password={pw} connect_timeout=5",row_factory=dict_row) as c:
    c.execute("select set_config('app.current_tenant','__SYSTEM__',false)")
    row=c.execute("select version,filename,checksum_sha256,applied_at from schema_migrations where version='0030_input_guard_v2'").fetchone()
    meta=c.execute("select key,value from schema_meta where key like 'input_guard_%' or key='schema_version' order by key").fetchall()
    print(dict(row) if row else None)
    print([dict(x) for x in meta])
