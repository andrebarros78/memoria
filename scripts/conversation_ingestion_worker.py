# ruff: noqa: E402,I001,BLE001
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from memory_permanent.access_policy import AgentAccessContext  # noqa: E402
from memory_permanent.canonical_mutation import CanonicalMutationService  # noqa: E402
from memory_permanent.conversation_ingestion import ConversationIngestionRepository  # noqa: E402
from memory_permanent.store import PostgresMemoryStore  # noqa: E402


def _safe_error(exc: Exception) -> str:
    text = str(exc)[:1000]
    text = re.sub(r"(?i)(password\s*=\s*)\S+", r"\1<redacted>", text)
    text = re.sub(r"(?i)(postgres(?:ql)?://[^:]+:)[^@]+@", r"\1<redacted>@", text)
    text = re.sub(r"((?:[A-Za-z0-9_.-]+|\[[^]]+\]):\d+:[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:)[^\s\"]+", r"\1<redacted>", text)
    return text


def dsn() -> str:
    configured = os.getenv("MEMORY_DATABASE_URL", "").strip()
    if configured:
        return configured
    passfile = ROOT / "runtime" / "secrets" / "pgpass.conf"
    if not passfile.is_file():
        raise RuntimeError("database credentials passfile is not provisioned")
    os.environ.setdefault("PGPASSFILE", str(passfile))
    return "postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary"



def run_once(limit: int) -> dict[str, object]:
    tenant = os.getenv("MEMORY_DEFAULT_TENANT", "LEGACY").strip().upper()
    store = PostgresMemoryStore(dsn(), initialize=False, tenant_id=tenant, access=AgentAccessContext.system())
    repo = ConversationIngestionRepository(store)
    mutations = CanonicalMutationService(store, actor_id="conversation-ingestion-worker")
    result = mutations.run_sanitized(
        "conversation.retry", repo.retry_pending,
        actor_id="conversation-ingestion-worker", limit=limit,
    )
    result["health"] = repo.health()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    log_path = ROOT / "runtime" / "logs" / "conversation-ingestion-worker.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        failed = False
        try:
            result = run_once(args.limit)
        except Exception as exc:  # noqa: BLE001
            failed = True
            result = {"status": "ERROR", "error_type": type(exc).__name__, "sqlstate": getattr(exc, "sqlstate", None), "error": _safe_error(exc)}
        line = json.dumps({"ts": time.time(), **result}, ensure_ascii=False, default=str)
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(line + "\n")
        if not args.loop:
            return 1 if failed or int(result.get("failed", 0)) > 0 else 0
        time.sleep(max(args.poll_seconds, 1.0))


if __name__ == "__main__":
    raise SystemExit(main())
