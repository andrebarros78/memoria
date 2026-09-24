import json
from pathlib import Path

import psycopg

ROOT=Path(r'C:\New Projet\MEMORIA-PERMANENTE')
raw=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip()
host,port,database,user,password=raw.split(':',4)
with psycopg.connect(host=host,port=int(port),dbname=database,user=user,password=password,connect_timeout=5) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT current_user, session_user, has_table_privilege(current_user,'public.conversation_ingestion_events','SELECT'), has_table_privilege(current_user,'public.conversation_ingestion_events','INSERT'), has_table_privilege(current_user,'public.conversation_ingestion_events','UPDATE'), has_table_privilege(current_user,'public.conversation_ingestion_events','DELETE')")
        r=cur.fetchone()
print(json.dumps({'current_user':r[0],'session_user':r[1],'select':r[2],'insert':r[3],'update':r[4],'delete':r[5]}))
