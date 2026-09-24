# ruff: noqa: E402,I001,BLE001
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]

from memory_permanent.access_policy import AgentAccessContext  # noqa: E402
from memory_permanent.canonical_mutation import CanonicalMutationService  # noqa: E402
from memory_permanent.embedding_provider import FastEmbedProvider  # noqa: E402
from memory_permanent.store import PostgresMemoryStore  # noqa: E402

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_DB = "memoria_permanente_v52_primary"


def _safe_error(exc: Exception) -> str:
    text = str(exc)[:1000]
    text = re.sub(r"(?i)(password\s*=\s*)\S+", r"\1<redacted>", text)
    text = re.sub(r"(?i)(postgres(?:ql)?://[^:]+:)[^@]+@", r"\1<redacted>@", text)
    text = re.sub(r"((?:[A-Za-z0-9_.-]+|\[[^]]+\]):\d+:[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:)[^\s\"]+", r"\1<redacted>", text)
    return text


def local_dsn() -> str:
    configured = os.getenv("MEMORY_DATABASE_URL", "").strip()
    if configured:
        return configured
    passfile = ROOT / "runtime" / "secrets" / "pgpass.conf"
    if not passfile.is_file():
        raise RuntimeError("database credentials passfile is not provisioned")
    os.environ.setdefault("PGPASSFILE", str(passfile))
    return f"postgresql://memory_app@127.0.0.1:55436/{DEFAULT_DB}"


def discovery_passfile() -> Path:
    configured = os.getenv("MEMORY_EMBEDDING_DISCOVERY_PGPASSFILE", "").strip()
    if configured:
        path = Path(configured)
    else:
        program_data = Path(os.getenv("PROGRAMDATA", r"C:\ProgramData"))
        path = program_data / "MemoriaPermanente" / "postgres" / "embedding-worker.pgpass.conf"
    if not path.is_file():
        raise RuntimeError("embedding discovery credential is not provisioned")
    return path


def discover_access_contexts(model_id: str, limit: int) -> list[dict[str, Any]]:
    dbname = os.getenv("MEMORY_DATABASE_NAME", DEFAULT_DB).strip() or DEFAULT_DB
    with psycopg.connect(
        host="127.0.0.1",
        port=55436,
        dbname=dbname,
        user="memory_embedding_worker",
        passfile=str(discovery_passfile()),
        connect_timeout=5,
        row_factory=dict_row,
    ) as conn:
        rows = conn.execute(
            "SELECT * FROM public.memory_embedding_access_contexts(%s,%s)",
            (model_id, min(max(int(limit), 1), 5000)),
        ).fetchall()
    return [dict(row) for row in rows]


def _access_context(row: dict[str, Any]) -> AgentAccessContext:
    scope = str(row.get("sharing_scope") or "SYSTEM_SHARED").strip().upper()
    agent_id = row.get("owner_agent_id") if scope == "AGENT_PRIVATE" else "embedding-worker"
    return AgentAccessContext.build(
        agent_id=str(agent_id) if agent_id else None,
        user_id=str(row["owner_user_id"]) if row.get("owner_user_id") else None,
        project_id=str(row["project_id"]) if row.get("project_id") else None,
        team_id=str(row["team_id"]) if row.get("team_id") else None,
        organization_id=str(row["organization_id"]) if row.get("organization_id") else None,
    )


def run_batch(store: PostgresMemoryStore, provider: FastEmbedProvider, limit: int) -> dict[str, object]:
    mutations = CanonicalMutationService(store, actor_id="embedding-worker")
    jobs = store.embedding_jobs(provider.model_id, limit=limit)
    embedded = 0
    failed = 0
    errors: list[dict[str, str]] = []
    if jobs:
        texts = [str(job["content_text"]) for job in jobs]
        try:
            vectors = provider.embed_documents(texts)
        except Exception as exc:  # noqa: BLE001
            vectors = []
            errors.append({"error_type": type(exc).__name__, "error": _safe_error(exc)[:500]})
        if len(vectors) == len(jobs):
            for job, vector in zip(jobs, vectors, strict=True):
                try:
                    mutations.store_embedding(
                        str(job["item_id"]),
                        model_id=provider.model_id,
                        dimensions=provider.dimensions,
                        embedding=vector,
                        content_sha256=str(job["content_sha256"]),
                    )
                    embedded += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    mutations.mark_embedding_failed(
                        str(job["item_id"]),
                        model_id=provider.model_id,
                        content_sha256=str(job["content_sha256"]),
                        error_type=type(exc).__name__,
                        error_message=_safe_error(exc),
                    )
                    errors.append({"item_id": str(job["item_id"]), "error_type": type(exc).__name__, "error": _safe_error(exc)[:500]})
        else:
            failed += len(jobs)
            errors.append({"error_type": "EmbeddingCountMismatch", "error": "provider result count did not match job count"})
    return {
        "model_id": provider.model_id,
        "dimensions": provider.dimensions,
        "jobs": len(jobs),
        "embedded": embedded,
        "failed": failed,
        "errors": errors,
    }


def run_scoped_batch(provider: FastEmbedProvider, limit: int) -> dict[str, object]:
    contexts = discover_access_contexts(provider.model_id, max(limit * 4, 100))
    remaining = min(max(int(limit), 1), 1000)
    total_jobs = 0
    total_embedded = 0
    total_failed = 0
    errors: list[dict[str, str]] = []
    contexts_processed = 0
    app_dsn = local_dsn()
    for row in contexts:
        if remaining <= 0:
            break
        tenant = str(row.get("tenant_id") or "").strip().upper()
        if not tenant:
            total_failed += 1
            errors.append({"error_type": "InvalidDiscoveryContext", "error": "missing tenant_id"})
            continue
        store = PostgresMemoryStore(
            app_dsn,
            initialize=False,
            tenant_id=tenant,
            access=_access_context(row),
        )
        result = run_batch(store, provider, remaining)
        contexts_processed += 1
        jobs = int(result["jobs"])
        total_jobs += jobs
        total_embedded += int(result["embedded"])
        total_failed += int(result["failed"])
        remaining -= jobs
        errors.extend(result.get("errors", []))
    return {
        "model_id": provider.model_id,
        "dimensions": provider.dimensions,
        "contexts_discovered": len(contexts),
        "contexts_processed": contexts_processed,
        "jobs": total_jobs,
        "embedded": total_embedded,
        "failed": total_failed,
        "errors": errors[:50],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.getenv("MEMORY_EMBEDDING_MODEL", DEFAULT_MODEL))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    args = parser.parse_args()
    log_path = ROOT / "runtime" / "logs" / "embedding-worker.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    provider = None
    while True:
        try:
            if provider is None:
                identity = os.getenv("MEMORY_EMBEDDING_IDENTITY", "").strip() or args.model
                provider = FastEmbedProvider(args.model, ROOT / "runtime" / "models" / "fastembed", threads=2, identity=identity)
            result = run_scoped_batch(provider, args.limit)
        except Exception as exc:  # noqa: BLE001
            result = {
                "model_id": getattr(provider, "model_id", args.model),
                "jobs": -1,
                "embedded": 0,
                "failed": 1,
                "errors": [{"error_type": type(exc).__name__, "sqlstate": getattr(exc, "sqlstate", None), "error": _safe_error(exc)}],
            }
        line = json.dumps({"ts": time.time(), **result}, ensure_ascii=False)
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
        if not args.loop:
            return 0 if int(result["failed"]) == 0 else 1
        time.sleep(max(1.0, args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())


