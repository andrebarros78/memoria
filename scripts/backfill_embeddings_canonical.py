from __future__ import annotations

import os
from pathlib import Path

from memory_permanent.canonical_mutation import CanonicalMutationService
from memory_permanent.embedding_provider import FastEmbedProvider
from memory_permanent.store import PostgresMemoryStore


def main() -> int:
    dsn=os.environ['MEMORY_DATABASE_URL']
    model=os.environ.get('MEMORY_EMBEDDING_MODEL','sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
    cache=os.environ.get('MEMORY_EMBEDDING_CACHE') or str(Path(__file__).resolve().parents[1]/'runtime'/'models'/'fastembed')
    store=PostgresMemoryStore(dsn,tenant_id='LEGACY',initialize=False)
    identity=os.environ.get("MEMORY_EMBEDDING_IDENTITY","").strip() or model
    provider=FastEmbedProvider(model_name=model,cache_dir=cache,threads=2,identity=identity)
    jobs=store.embedding_jobs(provider.model_id,limit=1000)
    mutations=CanonicalMutationService(store,actor_id='embedding-backfill')
    texts=[str(j['content_text']) for j in jobs]
    vectors=provider.embed_documents(texts) if texts else []
    for job,vec in zip(jobs,vectors,strict=True):
        mutations.store_embedding(str(job['item_id']),model_id=provider.model_id,dimensions=provider.dimensions,embedding=vec,content_sha256=str(job['content_sha256']))
    print(f'MODEL={provider.model_id}')
    print(f'DIMENSIONS={provider.dimensions}')
    print(f'JOBS={len(jobs)}')
    print(f'STORED={len(vectors)}')
    return 0
if __name__=='__main__':
    raise SystemExit(main())


