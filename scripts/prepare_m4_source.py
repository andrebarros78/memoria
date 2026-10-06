from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import time
import urllib.request
import uuid
from pathlib import Path

import psycopg

ROOT=Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0"); API='http://127.0.0.1:8787'
suffix=uuid.uuid4().hex[:12].upper(); tenant='TENANT_M4_'+suffix; ns='M4_RECOVERY_'+suffix; mission='m4-recovery-'+suffix.lower()
H={'Content-Type':'application/json','Accept':'application/json','X-Memory-Tenant':tenant}
def req(method,path,payload=None,extra=None):
 h=dict(H); h.update(extra or {}); data=None if payload is None else json.dumps(payload).encode(); r=urllib.request.Request(API+path,data=data,method=method,headers=h)
 with urllib.request.urlopen(r,timeout=60) as x: return json.loads(x.read().decode())  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.

def create(key,cat,text):
 p={'namespace':ns,'memory_key':key,'category':cat,'content':{'gate':'M4','key':key,'text':text,'revision':1},'content_text':text,'provenance':{'trusted':True,'proof':'M4_RECOVERY'},'confidence':1.0,'source':'sovereign-system','source_version':'M4','tags':['M4','RECOVERY'],'changed_by':'prepare_m4_source'}
 return req('POST','/v1/memories',p,{'Idempotency-Key':'m4-'+key+'-'+suffix})['item_id']
fact=create('recovery-fact','FACT','Estado M4 original antes do backup.')
doc=create('recovery-document','DOCUMENT','Documento M4 que deve sobreviver integralmente ao restore.')
time.sleep(.3)
rev={'content':{'gate':'M4','key':'recovery-fact','text':'Estado M4 corrigido e confirmado antes do backup.','revision':2},'content_text':'Estado M4 corrigido e confirmado antes do backup.','provenance':{'trusted':True,'proof':'M4_RECOVERY','corrects_revision':1},'confidence':1.0,'source':'sovereign-system','source_version':'M4','tags':['M4','RECOVERY','CORRECTED'],'changed_by':'prepare_m4_source'}
req('POST',f'/v1/memories/{fact}/versions',rev,{'Idempotency-Key':'m4-revise-'+suffix})
checkpoint=req('POST','/v1/checkpoints',{'namespace':ns,'mission_id':mission,'step_index':77,'state':{'gate':'M4','phase':'READY_FOR_BACKUP','objective':'restore real and resume checkpoint','fact_id':fact,'document_id':doc,'next_action':'RESTORE_AND_RESUME','counter':778899}})
worker=subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),str(ROOT/'scripts/embedding_worker.py'),'--limit','500'],cwd=str(ROOT),capture_output=True,text=True,timeout=180)  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.
raw=(ROOT/'runtime/secrets/pgpass.conf').read_text(encoding='ascii').strip(); host,port,db,user,pw=raw.split(':',4); dsn=f'host={host} port={port} dbname={db} user={user} password={pw} connect_timeout=5'
with psycopg.connect(dsn) as conn:
 conn.execute("SELECT set_config('app.current_tenant', %s, true)",(tenant,))
 items=conn.execute('SELECT item_id,memory_key,category,content_sha256,content_text FROM memory_items WHERE namespace=%s ORDER BY item_id',(ns,)).fetchall()
 versions=conn.execute('SELECT item_id,version_no,version_id,content_sha256,previous_version_id FROM memory_versions WHERE item_id=ANY(%s) ORDER BY item_id,version_no',([fact,doc],)).fetchall()
 embeddings=conn.execute('SELECT item_id,model_id,dimensions,content_sha256,status,embedding_vector::text FROM memory_embeddings WHERE item_id=ANY(%s) ORDER BY item_id',([fact,doc],)).fetchall()
 cp=conn.execute('SELECT checkpoint_id,mission_id,step_index,state_sha256,state_json FROM checkpoints WHERE checkpoint_id=%s',(checkpoint['checkpoint_id'],)).fetchone()
def canon(rows): return hashlib.sha256(json.dumps(rows,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
manifest={'generated_at':time.strftime('%Y-%m-%dT%H:%M:%S'),'tenant':tenant,'namespace':ns,'mission_id':mission,'fact_id':fact,'document_id':doc,'checkpoint_id':checkpoint['checkpoint_id'],'checkpoint_sha256':checkpoint['state_sha256'],'hashes':{'items':canon(items),'versions':canon(versions),'embeddings':canon(embeddings),'checkpoint':canon([cp])},'counts':{'items':len(items),'versions':len(versions),'embeddings':len(embeddings)},'worker_ok':worker.returncode==0}
(ROOT/'evidence/M4_SOURCE_MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps(manifest,indent=2))
raise SystemExit(0 if worker.returncode==0 and len(items)==2 and len(versions)==3 and len(embeddings)==2 else 1)
