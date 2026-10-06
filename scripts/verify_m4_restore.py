from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import psycopg

ROOT=Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0")
manifest=json.loads((ROOT/'evidence/M4_SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
port=int(sys.argv[1]); db=sys.argv[2]
dsn=f'host=127.0.0.1 port={port} dbname={db} user=postgres connect_timeout=5'
def canon(rows): return hashlib.sha256(json.dumps(rows,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
with psycopg.connect(dsn) as conn:
    conn.execute("SELECT set_config('app.current_tenant', %s, true)",(manifest['tenant'],))
    items=conn.execute('SELECT item_id,memory_key,category,content_sha256,content_text FROM memory_items WHERE namespace=%s ORDER BY item_id',(manifest['namespace'],)).fetchall()
    ids=[manifest['fact_id'],manifest['document_id']]
    versions=conn.execute('SELECT item_id,version_no,version_id,content_sha256,previous_version_id FROM memory_versions WHERE item_id=ANY(%s) ORDER BY item_id,version_no',(ids,)).fetchall()
    embeddings=conn.execute('SELECT item_id,model_id,dimensions,content_sha256,status,embedding_vector::text FROM memory_embeddings WHERE item_id=ANY(%s) ORDER BY item_id',(ids,)).fetchall()
    cp=conn.execute('SELECT checkpoint_id,mission_id,step_index,state_sha256,state_json FROM checkpoints WHERE checkpoint_id=%s',(manifest['checkpoint_id'],)).fetchone()
    ext=conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
    schema=conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
hashes={'items':canon(items),'versions':canon(versions),'embeddings':canon(embeddings),'checkpoint':canon([cp])}
counts={'items':len(items),'versions':len(versions),'embeddings':len(embeddings)}
checks={
 'ITEM_HASH_MATCH':hashes['items']==manifest['hashes']['items'],
 'VERSION_HASH_MATCH':hashes['versions']==manifest['hashes']['versions'],
 'EMBEDDING_HASH_MATCH':hashes['embeddings']==manifest['hashes']['embeddings'],
 'CHECKPOINT_HASH_MATCH':hashes['checkpoint']==manifest['hashes']['checkpoint'],
 'COUNTS_MATCH':counts==manifest['counts'],
 'CHECKPOINT_SHA256_MATCH':cp is not None and str(cp[3])==manifest['checkpoint_sha256'],
 'PGVECTOR_0_8_6':ext is not None and str(ext[0])=='0.8.6',
 'SCHEMA_0_6_0':schema is not None and str(schema[0])=='memory-0.6.0',
}
failed=[k for k,v in checks.items() if not v]
result={'database':db,'port':port,'tenant':manifest['tenant'],'hashes':hashes,'counts':counts,'checkpoint_id':manifest['checkpoint_id'],'checkpoint_sha256':None if cp is None else str(cp[3]),'checks':checks,'failed':failed,'PASS':not failed}
print(json.dumps(result,indent=2,default=str))
raise SystemExit(0 if not failed else 1)
