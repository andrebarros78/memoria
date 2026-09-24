import json
from pathlib import Path

import psycopg

ROOT=Path(r'C:\New Projet\MEMORIA-PERMANENTE')
pw=(ROOT/'runtime/secrets/postgres_admin.pw').read_text(encoding='utf-8-sig').strip()
with psycopg.connect(host='127.0.0.1',port=55436,dbname='memoria_permanente',user='memory_admin',password=pw,connect_timeout=5) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT pid,usename,state,wait_event_type,wait_event,left(query,200) FROM pg_stat_activity WHERE datname='memoria_permanente' AND pid<>pg_backend_pid() ORDER BY pid")
        rows=cur.fetchall()
print(json.dumps([{'pid':r[0],'user':r[1],'state':r[2],'wait_type':r[3],'wait_event':r[4],'query':r[5]} for r in rows],ensure_ascii=False))
