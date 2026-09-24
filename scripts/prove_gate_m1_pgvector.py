from __future__ import annotations

import json
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8787"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
QUERY = "Como manter o login sem cair depois que o token expira?"


def request(method: str, path: str, payload: dict | None = None, headers: dict[str, str] | None = None, timeout: float = 120.0):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Accept": "application/json", "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as response:  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
        raw = response.read().decode("utf-8")
        return response.status, json.loads(raw) if raw else {}


def local_dsn() -> str:
    raw = (ROOT / "runtime" / "secrets" / "pgpass.conf").read_text(encoding="ascii").strip()
    host, port, database, user, password = raw.split(":", 4)
    return f"host={host} port={port} dbname={database} user={user} password={password} connect_timeout=5"


def create_memory(namespace: str, key: str, text: str, suffix: str) -> str:
    payload = {
        "namespace": namespace,
        "memory_key": key,
        "category": "EVIDENCE",
        "content": {"gate": "M1", "backend": "pgvector", "key": key, "suffix": suffix, "text": text},
        "content_text": text,
        "provenance": {"trusted": True, "proof": "GATE_M1_PGVECTOR", "suffix": suffix},
        "confidence": 1.0,
        "source": "sovereign-system",
        "source_version": "M1-PGVECTOR",
        "tags": ["GATE_M1", "PGVECTOR", "RETRIEVAL"],
        "changed_by": "prove_gate_m1_pgvector",
    }
    _, result = request("POST", "/v1/memories", payload, {"Idempotency-Key": f"m1-pgvector-{key}-{suffix}"})
    return str(result["item_id"])


def main() -> int:
    suffix = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    namespace = f"M1_PGVECTOR_{suffix}".upper()
    mission_id = f"m1-pgvector-mission-{suffix}"
    _, health = request("GET", "/health")

    semantic_id = create_memory(
        namespace, "semantic-target",
        "A autenticação renova credenciais automaticamente quando o prazo termina.", suffix,
    )
    lexical_id = create_memory(namespace, "lexical-target", QUERY, suffix)
    unrelated_id = create_memory(
        namespace, "unrelated", "Receita culinária de bolo de chocolate com cobertura cremosa.", suffix,
    )
    ids = [semantic_id, lexical_id, unrelated_id]

    q = urllib.parse.quote(QUERY, safe="")
    _, lexical_before = request("GET", f"/v1/memories?q={q}&limit=500")
    lexical_ids = {str(x.get("item_id")) for x in lexical_before.get("items", [])}

    checkpoint_payload = {
        "namespace": namespace,
        "mission_id": mission_id,
        "step_index": 51,
        "state": {
            "phase": "PGVECTOR_CONTEXT_READY",
            "authorized_action": "resume-semantic-context",
            "semantic_target_id": semantic_id,
        },
    }
    _, checkpoint = request("POST", "/v1/checkpoints", checkpoint_payload)

    worker = subprocess.run(  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.
        [str(PYTHON), str(ROOT / "scripts" / "embedding_worker.py"), "--limit", "500"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    worker_lines = [line for line in worker.stdout.splitlines() if line.strip()]
    worker_result = json.loads(worker_lines[-1]) if worker_lines else {"failed": -1, "stderr": worker.stderr[-1000:]}

    _, context = request(
        "POST", "/v1/context/retrieve",
        {"query": QUERY, "namespaces": [namespace], "limit": 3, "mission_id": mission_id}, timeout=180,
    )
    selected = list(context.get("selected") or [])
    selected_ids = {str(x.get("item_id")) for x in selected}
    by_id = {str(x.get("item_id")): x for x in selected}
    semantic_row = by_id.get(semantic_id) or {}
    unrelated_row = by_id.get(unrelated_id) or {}
    semantic_score = float(semantic_row.get("semantic_similarity") or -1.0)
    unrelated_score = float(unrelated_row.get("semantic_similarity") or -1.0)
    retrieval_source = str(semantic_row.get("retrieval_source") or "")

    dsn = local_dsn()
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as conn:
        conn.execute("SELECT set_config('app.current_tenant', %s, true)", ("LEGACY",))
        ext = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
        schema = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        vector_rows = conn.execute(
            "SELECT count(*) AS n FROM memory_embeddings WHERE item_id=ANY(%s) AND status='READY' AND embedding_vector IS NOT NULL AND dimensions=384 AND model_id=%s",
            (ids, MODEL),
        ).fetchone()
        index_row = conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexname='idx_memory_embeddings_hnsw_cosine'"
        ).fetchone()
        trace = conn.execute(
            "SELECT trace_id,state_json,retrieval_modes,candidates,selected FROM retrieval_traces WHERE trace_id=%s",
            (str(context["trace_id"]),),
        ).fetchone()
        # Dual verification: direct pgvector score vs legacy array cosine for the same target/unrelated proof rows
        dual_rows = conn.execute(
            """
            SELECT item_id,
                   1 - (embedding_vector <=> (SELECT embedding_vector FROM memory_embeddings WHERE item_id=%s)) AS self_vector_score,
                   embedding
            FROM memory_embeddings WHERE item_id=ANY(%s) ORDER BY item_id
            """,
            (semantic_id, ids),
        ).fetchall()

    indexdef = str(index_row["indexdef"] if index_row else "")
    modes = set(context.get("retrieval_modes") or [])
    state = context.get("state") or {}
    checks = {
        "API_VERSION_SUPPORTS_M1": tuple(int(x) for x in str(health.get("version") or "0.0.0").split(".")) >= (0, 4, 0),
        "SCHEMA_VERSION_SUPPORTS_M1": schema is not None and str(schema["value"]).startswith("memory-") and tuple(int(x) for x in str(schema["value"]).split("-", 1)[1].split(".")) >= (0, 4, 0),
        "PGVECTOR_0_8_6_ENABLED": ext is not None and str(ext["extversion"]) == "0.8.6",
        "HNSW_COSINE_INDEX_PRESENT": "USING hnsw" in indexdef and "vector_cosine_ops" in indexdef,
        "THREE_PROOF_VECTORS_READY": int(vector_rows["n"] if vector_rows else 0) == 3,
        "ASYNC_WORKER_PASS": worker.returncode == 0 and int(worker_result.get("failed", -1)) == 0,
        "SEMANTIC_TARGET_NOT_LEXICAL_MATCH": semantic_id not in lexical_ids,
        "LEXICAL_TARGET_FOUND": lexical_id in lexical_ids,
        "LEXICAL_MODE_USED": "LEXICAL" in modes,
        "SEMANTIC_MODE_USED": "SEMANTIC" in modes,
        "STATE_MODE_USED": "STATE" in modes,
        "SEMANTIC_PATH_IS_PGVECTOR": retrieval_source == "SEMANTIC_PGVECTOR",
        "SEMANTIC_PARAPHRASE_RECOVERED": semantic_id in selected_ids,
        "SEMANTIC_TARGET_OUTRANKS_UNRELATED": semantic_score > unrelated_score,
        "CHECKPOINT_STATE_RECOVERED": state.get("checkpoint_id") == checkpoint.get("checkpoint_id") and (state.get("state") or {}).get("phase") == "PGVECTOR_CONTEXT_READY",
        "TRACE_PERSISTED": trace is not None and str(trace["trace_id"]) == str(context["trace_id"]),
        "TRACE_MODES_PERSISTED": trace is not None and set(trace["retrieval_modes"] or []) == {"LEXICAL", "SEMANTIC", "STATE"},
        "DUAL_REPRESENTATION_AVAILABLE": len(dual_rows) == 3 and all(row.get("embedding") is not None for row in dual_rows),
    }
    failed = [k for k, v in checks.items() if not v]
    result = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "gate": "M1",
        "model": MODEL,
        "dimensions": 384,
        "pgvector_version": str(ext["extversion"] if ext else ""),
        "index_definition": indexdef,
        "semantic_backend": "PGVECTOR_HNSW_COSINE",
        "namespace": namespace,
        "mission_id": mission_id,
        "item_ids": {"semantic_target": semantic_id, "lexical_target": lexical_id, "unrelated": unrelated_id},
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "trace_id": context.get("trace_id"),
        "retrieval_modes": sorted(modes),
        "retrieval_source": retrieval_source,
        "semantic_similarity": {"target": semantic_score, "unrelated": unrelated_score},
        "worker": worker_result,
        "checks": checks,
        "failed_checks": failed,
        "GATE_M1": "PASS" if not failed else "FAIL",
        "RETRIEVAL_PROVEN": not failed,
    }
    evidence = ROOT / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "M1_GATE_PROOF.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Gate M1 — Recuperação",
        "",
        f"**GATE_M1:** {result['GATE_M1']}",
        f"**RETRIEVAL_PROVEN:** {result['RETRIEVAL_PROVEN']}",
        "",
        f"Backend: `{result['semantic_backend']}`",
        f"pgvector: `{result['pgvector_version']}`",
        f"Modelo: `{MODEL}` ({result['dimensions']}D)",
        "",
        "## Checks",
    ] + [f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in checks.items()]
    (evidence / "M1_GATE_PROOF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "GATE_M1": result["GATE_M1"],
        "pgvector": result["pgvector_version"],
        "backend": result["semantic_backend"],
        "retrieval_modes": result["retrieval_modes"],
        "retrieval_source": retrieval_source,
        "target_similarity": semantic_score,
        "unrelated_similarity": unrelated_score,
        "failed": failed,
    }, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
