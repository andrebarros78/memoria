from __future__ import annotations

import json
import os

import psycopg
from psycopg import sql

src=psycopg.connect('postgresql://postgres@127.0.0.1:55436/memoria_permanente')
dst=psycopg.connect('postgresql://postgres@127.0.0.1:55436/'+os.environ['RESTORE_DB'])
try:
    q="select tablename from pg_tables where schemaname='public' order by tablename"
    a=[r[0] for r in src.execute(q).fetchall()]
    b=[r[0] for r in dst.execute(q).fetchall()]
    mism={}
    for table in a:
        stmt=sql.SQL('select count(*) from {}').format(sql.Identifier(table))
        x=src.execute(stmt).fetchone()[0]
        y=dst.execute(stmt).fetchone()[0]
        if x != y:
            mism[table]=[x,y]
    out={'table_sets_equal':a==b,'source_table_count':len(a),'restore_table_count':len(b),'row_counts_equal':not mism,'row_count_mismatches':mism}
    print(json.dumps(out,indent=2))
    raise SystemExit(0 if out['table_sets_equal'] and out['row_counts_equal'] else 2)
finally:
    src.close(); dst.close()