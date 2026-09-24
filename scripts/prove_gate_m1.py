from __future__ import annotations

import json
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
import time
import urllib.error
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
QUERY = "Como manter o login sem cair depois que o token expira?"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def request(method: str, path: str, payload: dict | None = None, headers: dict[str, str] | None = None, timeout: float = 90.0):
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
        "content": {"gate": "M1", "key": key, "suffix": suffix, "text": text},
        "content_text": text,
        "provenance": {"trusted": True, "proof": "GATE_M1", "suffix": suffix},
        "confidence": 1.0,
        "source": "sovereign-system",
        "source_version": "M1-PROOF",
        "tags": ["GATE_M1", "RETRIEVAL"],
        "changed_by": "prove_gate_m1",
    }
    _, result = request("POST", "/v1/memories", payload, {"Idempotency-Key": f"m1-{key}-{suffix}"})
    return str(result["item_id"])


def main() -> int:
    suffix = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    namespace = f"M1_PROOF_{suffix}".upper()
    mission_id = f"m1-mission-{suffix}"
    _, health = request("GET", "/health")
    target_id = create_memory(
        namespace,
        "semantic-target",
        "A autenticação renova credenciais automaticamente quando o prazo termina.",
        suffix,
    )
    lexical_id = create_memory(
        namespace,
        "lexical-target",
        QUERY,
        suffix,
    )
    unrelated_id = create_memory(
        namespace,
        "unrelated",
        "Receita culinária de bolo de chocolate com cobertura cremosa.",
        suffix,
    )
    ids = [target_id, lexical_id, unrelated_id]

    q = urllib.parse.quote(QUERY, safe="")
    _, lexical_before = request("GET", f"/v1/memories?q={q}&limit=500")
    lexical_ids = {str(x.get("item_id")) for x in lexical_before.get("items", [])}

    dsn = local_dsn()
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as conn:
        before_embeddings = conn.execute(
            "SELECT count(*) AS n FROM memory_embeddings WHERE item_id=ANY(%s) AND status='READY'", (ids,)
        ).fetchone()["n"]
        schema_version = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()["value"]

    checkpoint_payload = {
        "namespace": namespace,
        "mission_id": mission_id,
        "step_index": 42,
        "state": {
            "phase": "RECOVERY_READY",
            "provider": "provider-A",
            "authorized_action": "resume-from-checkpoint",
            "semantic_target_id": target_id,
        },
    }
    _, checkpoint = request("POST", "/v1/checkpoints", checkpoint_payload)

    worker = subprocess.run(  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.
        [str(PYTHON), str(ROOT / "scripts" / "embedding_worker.py"), "--limit", "500"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    worker_lines = [line for line in worker.stdout.splitlines() if line.strip()]
    worker_result = json.loads(worker_lines[-1]) if worker_lines else {"failed": -1, "error": worker.stderr[-1000:]}

    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as conn:
        ready_rows = conn.execute(
            "SELECT item_id,model_id,dimensions,status FROM memory_embeddings WHERE item_id=ANY(%s) ORDER BY item_id", (ids,)
        ).fetchall()

    _, context = request(
        "POST",
        "/v1/context/retrieve",
        {"query": QUERY, "namespaces": [namespace], "limit": 3, "mission_id": mission_id},
        timeout=120,
    )
    selected = list(context.get("selected") or [])
    selected_ids = {str(x.get("item_id")) for x in selected}
    by_id = {str(x.get("item_id")): x for x in selected}
    semantic_score = float((by_id.get(target_id) or {}).get("semantic_similarity") or -1.0)
    unrelated_score = float((by_id.get(unrelated_id) or {}).get("semantic_similarity") or -1.0)

    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as conn:
        trace = conn.execute(
            "SELECT trace_id,state_json,retrieval_modes,candidates,selected,created_at FROM retrieval_traces WHERE trace_id=%s",
            (str(context["trace_id"]),),
        ).fetchone()
        provider_count = conn.execute(
            "SELECT count(*) AS n FROM memory_embeddings WHERE item_id=ANY(%s) AND model_id=%s AND status='READY' AND dimensions=384",
            (ids, MODEL),
        ).fetchone()["n"]

    modes = set(context.get("retrieval_modes") or [])
    state = context.get("state") or {}
    checks = {
        "API_VERSION_0_3_0": health.get("version") == "0.3.0",
        "SCHEMA_VERSION_0_3_0": str(schema_version) == "memory-0.3.0",
        "CANONICAL_WRITE_PRECEDES_EMBEDDING": int(before_embeddings) == 0,
        "SEMANTIC_TARGET_NOT_LEXICALLY_MATCHED": target_id not in lexical_ids,
        "LEXICAL_TARGET_FOUND": lexical_id in lexical_ids,
        "ASYNC_EMBEDDING_WORKER_PASS": worker.returncode == 0 and int(worker_result.get("failed", -1)) == 0,
        "THREE_PROOF_EMBEDDINGS_READY": len(ready_rows) == 3 and int(provider_count) == 3,
        "LEXICAL_MODE_USED": "LEXICAL" in modes,
        "SEMANTIC_MODE_USED": "SEMANTIC" in modes,
        "STATE_MODE_USED": "STATE" in modes,
        "SEMANTIC_PARAPHRASE_RECOVERED": target_id in selected_ids,
        "SEMANTIC_TARGET_OUTRANKS_UNRELATED": semantic_score > unrelated_score,
        "CHECKPOINT_STATE_IN_CONTEXT": state.get("checkpoint_id") == checkpoint.get("checkpoint_id") and (state.get("state") or {}).get("phase") == "RECOVERY_READY",
        "TRACE_PERSISTED": trace is not None and str(trace["trace_id"]) == str(context["trace_id"]),
        "TRACE_MODES_PERSISTED": trace is not None and set(trace["retrieval_modes"] or []) == {"LEXICAL", "SEMANTIC", "STATE"},
        "TRACE_STATE_PERSISTED": trace is not None and (trace["state_json"] or {}).get("checkpoint_id") == checkpoint.get("checkpoint_id"),
    }
    failed = [k for k, v in checks.items() if not v]
    result = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "gate": "M1",
        "namespace": namespace,
        "mission_id": mission_id,
        "model": MODEL,
        "dimensions": 384,
        "semantic_backend": "POSTGRES_DOUBLE_ARRAY_PLUS_LOCAL_COSINE",
        "pgvector_installed": False,
        "pgvector_release_conformance": False,
        "item_ids": {"semantic_target": target_id, "lexical_target": lexical_id, "unrelated": unrelated_id},
        "checkpoint_id": checkpoint.get("checkpoint_id"),
        "worker": worker_result,
        "semantic_similarity": {"target": semantic_score, "unrelated": unrelated_score},
        "retrieval_modes": sorted(modes),
        "trace_id": context.get("trace_id"),
        "checks": checks,
        "failed_checks": failed,
        "M1_FUNCTIONAL_RETRIEVAL_PROOF": "PASS" if not failed else "FAIL",
        "GATE_M1": "BLOCKED_PGVECTOR_0_8_6" if not failed else "FAIL",
    }
    evidence = ROOT / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "M1_FUNCTIONAL_RETRIEVAL_PROOF.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Gate M1 — Recuperação",
        "",
        f"**M1_FUNCTIONAL_RETRIEVAL_PROOF:** {result['M1_FUNCTIONAL_RETRIEVAL_PROOF']}",
        f"**GATE_M1:** {result['GATE_M1']}",
        "",
        f"Modelo local: `{MODEL}`",
        "Dimensões: 384",
        f"Backend semântico atual: `{result['semantic_backend']}`",
        "",
        "> A funcionalidade lexical + semântica + estado foi comprovada, mas o Gate M1 não é fechado enquanto pgvector 0.8.6 não for instalado, conforme ADR-MEM-003 e seção 7.2 da V4.",
        "",
        "## Checks",
    ] + [f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in checks.items()]
    (evidence / "M1_FUNCTIONAL_RETRIEVAL_PROOF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "M1_FUNCTIONAL_RETRIEVAL_PROOF": result["M1_FUNCTIONAL_RETRIEVAL_PROOF"],
        "GATE_M1": result["GATE_M1"],
        "retrieval_modes": result["retrieval_modes"],
        "target_similarity": semantic_score,
        "unrelated_similarity": unrelated_score,
        "failed": failed,
    }, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
