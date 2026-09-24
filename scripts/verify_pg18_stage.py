from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import sql as pg_sql
from psycopg.rows import dict_row

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/'src'
if str(SRC) not in sys.path: sys.path.insert(0,str(SRC))
from memory_permanent.store import PostgresMemoryStore  # noqa: E402

admin=(ROOT/'runtime/secrets/postgres_admin.pw').read_text(encoding='utf-8').strip()
def dsn(port:int)->str:return f'host=127.0.0.1 port={port} dbname=memoria_permanente user=memory_admin password={admin} connect_timeout=5'
def norm(v):
    if v is None or isinstance(v,(str,int,float,bool)): return v
    if isinstance(v,(bytes,bytearray,memoryview)): return {'__bytes__':bytes(v).hex()}
    if isinstance(v,(datetime,date,time)): return {'__time__':v.isoformat()}
    if isinstance(v,(Decimal,UUID)): return str(v)
    if isinstance(v,dict): return {str(k):norm(x) for k,x in sorted(v.items(),key=lambda z:str(z[0]))}
    if isinstance(v,(list,tuple,set)): return [norm(x) for x in v]
    return str(v)
def table_manifest(conn,name):
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(pg_sql.SQL('SELECT * FROM public.{}').format(pg_sql.Identifier(name)))
        rows=[json.dumps(norm(dict(r)),ensure_ascii=False,sort_keys=True,separators=(',',':')) for r in cur.fetchall()]
    rows.sort(); blob='\n'.join(rows).encode('utf-8')
    return {'rows':len(rows),'sha256':hashlib.sha256(blob).hexdigest()}
def snapshot(port):
    with psycopg.connect(dsn(port),row_factory=dict_row) as c:
        tables=[r['tablename'] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()]
        manifests={t:table_manifest(c,t) for t in tables}
        meta=c.execute("SELECT current_setting('server_version') server_version,(SELECT extversion FROM pg_extension WHERE extname='vector') vector_version,(SELECT value FROM schema_meta WHERE key='schema_version') schema_version,(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()) db_owner").fetchone()
        rls=c.execute("SELECT count(*) policies FROM pg_policies WHERE schemaname='public'").fetchone()['policies']
        forced=c.execute("SELECT count(*) forced FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relforcerowsecurity").fetchone()['forced']
        idx=c.execute("SELECT count(*) n FROM pg_indexes WHERE schemaname='public'").fetchone()['n']
        con=c.execute("SELECT count(*) n FROM pg_constraint co JOIN pg_namespace n ON n.oid=co.connamespace WHERE n.nspname='public'").fetchone()['n']
    return {'meta':dict(meta),'tables':manifests,'rls_policies':rls,'force_rls_tables':forced,'indexes':idx,'constraints':con}
def main():
    src=snapshot(55436); dst=snapshot(55438)
    table_names_equal=set(src['tables'])==set(dst['tables'])
    mismatches=[]
    for t in sorted(set(src['tables'])|set(dst['tables'])):
        if src['tables'].get(t)!=dst['tables'].get(t):mismatches.append(t)
    audit=PostgresMemoryStore(dsn(55438),initialize=False,tenant_id='__SYSTEM__').verify_audit_chain()
    checks={
      'TARGET_POSTGRES_18_6':str(dst['meta']['server_version']).startswith('18.6'),
      'TARGET_PGVECTOR_0_8_6':dst['meta']['vector_version']=='0.8.6',
      'SCHEMA_VERSION_EQUAL':src['meta']['schema_version']==dst['meta']['schema_version'],
      'DATABASE_OWNER_EQUAL':src['meta']['db_owner']==dst['meta']['db_owner']=='memory_app',
      'TABLE_SET_EQUAL':table_names_equal,
      'ALL_TABLE_ROW_COUNTS_AND_CONTENT_HASHES_EQUAL':not mismatches,
      'RLS_POLICY_COUNT_EQUAL':src['rls_policies']==dst['rls_policies'],
      'FORCE_RLS_COUNT_EQUAL':src['force_rls_tables']==dst['force_rls_tables'],
      'INDEX_COUNT_EQUAL':src['indexes']==dst['indexes'],
      'CONSTRAINT_COUNT_EQUAL':src['constraints']==dst['constraints'],
      'TARGET_AUDIT_CHAIN_VALID':bool(audit.get('ok')),
    }
    failed=[k for k,v in checks.items() if not v]
    result={'proof':'PG18_STAGE_PARITY','source':src,'target':dst,'mismatched_tables':mismatches,'audit':audit,'checks':checks,'failed_checks':failed,'PG18_STAGE_PARITY_PROOF':'PASS' if not failed else 'FAIL'}
    (ROOT/'evidence/PG18_STAGE_PARITY_PROOF.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'PG18_STAGE_PARITY_PROOF':result['PG18_STAGE_PARITY_PROOF'],'tables':len(dst['tables']),'mismatched_tables':mismatches,'rls':dst['rls_policies'],'force_rls':dst['force_rls_tables'],'indexes':dst['indexes'],'constraints':dst['constraints'],'audit_ok':audit.get('ok'),'failed':failed},ensure_ascii=False,indent=2))
    return 0 if not failed else 1
if __name__=='__main__':raise SystemExit(main())
