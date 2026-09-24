from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, r"C:\New Projet\MEMORIA-CLIENT-ADAPTER\src")
from memoria_client_adapter import (  # noqa: E402
    MemoryClientAdapter,
    WindowsDpapiCredentialProvider,
)

AUTH = Path(os.getenv("ProgramData", r"C:\ProgramData")) / "MemoriaPermanente" / "auth" / "clients" / "local-admin.dpapi"
BASE = "http://127.0.0.1:8787"
DSN = "postgresql://memory_app@127.0.0.1:55436/memoria_permanente"
MIGRATION = ROOT / "migrations" / "0026_global_user_memory_scope.sql"
MIGRATION_SHA = "37f399b203d757280d8e9ae247eb6543154bb472f2102ae83245cf4b1d7bb043"
client = MemoryClientAdapter(BASE, client_id="local-admin", credential_provider=WindowsDpapiCredentialProvider(AUTH))


def unsigned_status(path: str) -> int:
    try:
        urllib.request.urlopen(BASE + path, timeout=5)  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
        return 200
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def request(method: str, path: str, payload=None, headers=None):
    return client.request(method, path, payload=payload, headers=headers)


def create_memory(ns: str, key: str, token: str, scope: str | None = None, ref: str | None = None, *, sharing_scope: str = "SYSTEM_SHARED", project_id: str | None = None, headers=None):
    payload = {
        "namespace": ns,
        "memory_key": key,
        "category": "FACT",
        "content": {"token": token, "semantic_scope": scope or "DEFAULT"},
        "content_text": f"{token} {key}",
        "provenance": {"proof": "MEMORIA_PLUS_P11"},
        "confidence": 1.0,
        "source": "memoria-plus-p11-proof",
        "tags": ["MEMORIA PLUS", "P11_PROOF"],
        "sharing_scope": sharing_scope,
    }
    if scope is not None:
        payload["memory_scope"] = scope
    if ref is not None:
        payload["memory_scope_ref"] = ref
    if project_id is not None:
        payload["project_id"] = project_id
    return request("POST", "/v1/memories", payload, headers=headers)


def sqlstate_for(sql: str, params=()) -> str | None:
    conn = psycopg.connect(DSN, row_factory=dict_row)
    try:
        conn.execute("select set_config('app.current_tenant','__SYSTEM__',false)")
        try:
            conn.execute(sql, params)
            conn.rollback()
            return None
        except psycopg.Error as exc:
            state = exc.sqlstate
            conn.rollback()
            return state
    finally:
        conn.close()


run = uuid.uuid4().hex[:12].upper()
ns = f"P11_PROOF_{run}"
token = f"P11_SCOPE_TOKEN_{run}"
project_ref = f"project-{run.lower()}"
mission_ref = f"mission-{run.lower()}"
session_ref = f"session-{run.lower()}"

checks: dict[str, bool] = {}
detail: dict[str, object] = {}

status, health = request("GET", "/health")
checks["api_0_19_0"] = status == 200 and health.get("version") == "0.19.0"
checks["scope_spec_requires_auth"] = unsigned_status("/v1/memory-scopes") == 401
status, spec = request("GET", "/v1/memory-scopes")
checks["scope_spec_version"] = status == 200 and spec.get("version") == "MS-1.0.0"
checks["exact_four_semantic_scopes"] = spec.get("scopes") == ["GLOBAL_USER", "PROJECT", "MISSION", "SESSION"]
checks["global_user_is_canonical"] = spec.get("canonical_global_scope") == "GLOBAL_USER"
checks["general_memory_is_human_label_only"] = spec.get("general_memory_human_label") == "Mem\u00f3ria Geral" and spec.get("separation", {}).get("memory_scope_is_acl") is False

# API validation and code-space separation.
base_invalid = {
    "namespace": ns, "memory_key": "invalid", "category": "FACT", "content": {"x": 1}, "content_text": token,
    "provenance": {"proof": "P11"}, "confidence": 1.0, "source": "p11", "tags": ["P11"], "sharing_scope": "SYSTEM_SHARED",
}
st, _ = request("POST", "/v1/memories", {**base_invalid, "memory_scope": "SYSTEM_SHARED"})
checks["sharing_code_rejected_as_memory_scope"] = st == 422
st, _ = request("POST", "/v1/memories", {**base_invalid, "memory_key": "invalid-sharing", "memory_scope": "GLOBAL_USER", "sharing_scope": "GLOBAL_USER"})
checks["global_user_rejected_as_sharing_scope"] = st == 422
st, _ = request("POST", "/v1/memories", {**base_invalid, "memory_key": "project-no-ref", "memory_scope": "PROJECT"})
checks["project_requires_reference"] = st == 422
st, _ = request("POST", "/v1/memories", {**base_invalid, "memory_key": "global-with-ref", "memory_scope": "GLOBAL_USER", "memory_scope_ref": "forbidden"})
checks["global_user_forbids_reference"] = st == 422

# Create one memory in each semantic scope. Default must resolve to GLOBAL_USER.
created: dict[str, str] = {}
for key, scope, ref in [
    ("global", None, None),
    ("project", "PROJECT", project_ref),
    ("mission", "MISSION", mission_ref),
    ("session", "SESSION", session_ref),
]:
    st, body = create_memory(ns, key, token, scope, ref)
    checks[f"create_{key}_scope"] = st == 201 and bool(body.get("item_id"))
    created[key] = str(body.get("item_id") or "")

# List API returns canonical semantic metadata and enforces reference pairing.
for key, scope, ref in [
    ("global", "GLOBAL_USER", None),
    ("project", "PROJECT", project_ref),
    ("mission", "MISSION", mission_ref),
    ("session", "SESSION", session_ref),
]:
    path = f"/v1/memories?q={token}&memory_scope={scope}" + (f"&memory_scope_ref={ref}" if ref else "")
    st, body = request("GET", path)
    rows = body.get("items", []) if isinstance(body, dict) else []
    checks[f"list_{key}_scope_exact"] = st == 200 and any(row.get("item_id") == created[key] and row.get("memory_scope") == scope and row.get("memory_scope_ref") == ref for row in rows)
st, _ = request("GET", f"/v1/memories?q={token}&memory_scope_ref={session_ref}")
checks["list_ref_requires_scope"] = st == 422

# Context retrieval: GLOBAL_USER always participates; contextual scopes only on matching references.
def selected_ids(payload: dict, headers=None) -> tuple[int, set[str]]:
    st, body = request("POST", "/v1/context/retrieve", payload, headers=headers)
    return st, {str(row.get("item_id")) for row in body.get("selected", [])} if isinstance(body, dict) else set()

common = {"query": token, "namespaces": [ns], "limit": 10}
st, ids = selected_ids(common)
checks["context_without_selector_is_global_user_only"] = st == 200 and created["global"] in ids and all(created[k] not in ids for k in ("project", "mission", "session"))
st, ids = selected_ids({**common, "mission_id": mission_ref})
checks["mission_context_adds_mission_scope"] = st == 200 and {created["global"], created["mission"]}.issubset(ids) and created["session"] not in ids
st, ids = selected_ids({**common, "session_id": session_ref})
checks["session_context_adds_session_scope"] = st == 200 and {created["global"], created["session"]}.issubset(ids) and created["mission"] not in ids
st, ids = selected_ids(common, headers={"X-Memory-Project": project_ref})
checks["project_context_adds_project_scope"] = st == 200 and {created["global"], created["project"]}.issubset(ids)
st, ids = selected_ids({**common, "mission_id": mission_ref, "session_id": session_ref}, headers={"X-Memory-Project": project_ref})
checks["combined_context_resolves_all_four_scopes"] = st == 200 and set(created.values()).issubset(ids)

# Explicit independence: SESSION semantic scope can carry PROJECT_SHARED ACL metadata.
acl_project = f"acl-{run.lower()}"
acl_session = f"acl-session-{run.lower()}"
try:
    st, body = create_memory(ns, "independent-dimensions", token, "SESSION", acl_session, sharing_scope="PROJECT_SHARED", project_id=acl_project, headers={"X-Memory-Project": acl_project})
    independence_id = str(body.get("item_id") or "") if isinstance(body, dict) else ""
    st2, listing = request("GET", f"/v1/memories?q={token}&memory_scope=SESSION&memory_scope_ref={acl_session}", headers={"X-Memory-Project": acl_project})
    rows = listing.get("items", []) if isinstance(listing, dict) else []
    checks["semantic_scope_and_sharing_acl_independent"] = st == 201 and st2 == 200 and any(row.get("item_id") == independence_id and row.get("memory_scope") == "SESSION" and row.get("sharing_scope") == "PROJECT_SHARED" for row in rows)
except (OSError, RuntimeError, ValueError):
    checks["semantic_scope_and_sharing_acl_independent"] = False

# PostgreSQL enforcement and migration evidence.
with psycopg.connect(DSN, row_factory=dict_row) as conn:
    conn.execute("select set_config('app.current_tenant','__SYSTEM__',false)")
    meta = {row["key"]: row["value"] for row in conn.execute("select key,value from schema_meta where key in ('schema_version','memory_scope_version','memory_scope_canonical_global','memory_scope_general_label','memory_scope_legacy_backfill_count')").fetchall()}
    invalid_count = conn.execute("""select count(*) n from memory_items where memory_scope not in ('GLOBAL_USER','PROJECT','MISSION','SESSION') or (memory_scope='GLOBAL_USER' and memory_scope_ref is not null) or (memory_scope in ('PROJECT','MISSION','SESSION') and (memory_scope_ref is null or length(btrim(memory_scope_ref))=0))""").fetchone()["n"]
    policy = conn.execute("select qual,with_check from pg_policies where tablename='memory_items' and policyname='tenant_and_agent_isolation'").fetchone()
    rls = conn.execute("select relrowsecurity,relforcerowsecurity from pg_class where oid='memory_items'::regclass").fetchone()
    migration = conn.execute("select checksum_sha256 from schema_migrations where version='0026_global_user_memory_scope'").fetchone()
    columns = {r["column_name"]: r for r in conn.execute("select column_name,is_nullable,column_default from information_schema.columns where table_name='memory_items' and column_name in ('memory_scope','memory_scope_ref','sharing_scope')").fetchall()}
    matches = conn.execute("select memory_scope_matches_context('GLOBAL_USER',null,'','','') g, memory_scope_matches_context('PROJECT',%s,%s,'','') p, memory_scope_matches_context('MISSION',%s,'',%s,'') m, memory_scope_matches_context('SESSION',%s,'','',%s) s",(project_ref,project_ref,mission_ref,mission_ref,session_ref,session_ref)).fetchone()

checks["schema_version"] = meta.get("schema_version") == "memory-0.19.0"
checks["memory_scope_schema_version"] = meta.get("memory_scope_version") == "MS-1.0.0"
checks["canonical_global_meta"] = meta.get("memory_scope_canonical_global") == "GLOBAL_USER"
checks["legacy_backfill_exact"] = meta.get("memory_scope_legacy_backfill_count") == "1186"
checks["all_persisted_scopes_canonical"] = int(invalid_count) == 0
checks["memory_scope_columns_enforced"] = columns.get("memory_scope", {}).get("is_nullable") == "NO" and "GLOBAL_USER" in str(columns.get("memory_scope", {}).get("column_default"))
policy_text = (str(policy.get("qual")) + " " + str(policy.get("with_check"))).lower() if policy else ""
checks["rls_acl_uses_sharing_not_semantic_scope"] = bool(policy) and "sharing_scope" in policy_text and "memory_scope" not in policy_text
checks["memory_items_force_rls"] = bool(rls and rls.get("relrowsecurity") and rls.get("relforcerowsecurity"))
checks["db_context_match_function_exact"] = bool(matches and all(bool(matches[k]) for k in ("g", "p", "m", "s")))
checks["migration_0026_checksum"] = bool(migration and migration.get("checksum_sha256") == MIGRATION_SHA and hashlib.sha256(MIGRATION.read_bytes()).hexdigest() == MIGRATION_SHA)

# SQL bypasses fail closed.
clone_sql = """insert into memory_items(item_id,namespace,memory_key,category,content_json,content_text,provenance,confidence,source,source_version,tags,content_sha256,memory_scope,memory_scope_ref,sharing_scope,owner_user_id,owner_agent_id,project_id,team_id,organization_id,validation_status,governor_eligible) select %s,namespace,%s,category,content_json,content_text,provenance,confidence,source,source_version,tags,content_sha256,%s,%s,sharing_scope,owner_user_id,owner_agent_id,project_id,team_id,organization_id,'UNVALIDATED',false from memory_items where item_id=%s"""
checks["schema_invalid_scope_rejected"] = sqlstate_for(clone_sql, (f"mem-invalid-{uuid.uuid4().hex}", f"invalid.{run}", "INVALID_SCOPE", None, created["global"])) == "23514"
checks["schema_global_ref_rejected"] = sqlstate_for(clone_sql, (f"mem-invalid-{uuid.uuid4().hex}", f"invalid-global.{run}", "GLOBAL_USER", "forbidden", created["global"])) == "23514"
checks["semantic_scope_immutable"] = sqlstate_for("update memory_items set memory_scope='SESSION',memory_scope_ref='forbidden' where item_id=%s", (created["global"],)) == "42501"

# Producers that own an actual session now use SESSION semantic scope explicitly.
ingestion_source = (ROOT / "src" / "memory_permanent" / "conversation_ingestion.py").read_text(encoding="utf-8")
rotation_source = (ROOT / "src" / "memory_permanent" / "session_rotation.py").read_text(encoding="utf-8")
checks["conversation_ingestion_uses_session_semantic_scope"] = 'memory_scope="SESSION", memory_scope_ref=session_id' in ingestion_source
checks["session_rotation_uses_session_semantic_scope"] = 'memory_scope="SESSION", memory_scope_ref=session_id' in rotation_source

failed = [name for name, ok in checks.items() if not ok]
result = {
    "result": "PASS" if not failed else "FAIL",
    "failed": failed,
    "checks": checks,
    "schema": meta.get("schema_version"),
    "memory_scope_version": meta.get("memory_scope_version"),
    "legacy_backfill_count": int(meta.get("memory_scope_legacy_backfill_count") or 0),
    "created_scope_items": created,
    "migration_0026_sha256": MIGRATION_SHA,
}

json_bytes = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")
md_lines = [
    "# MEMORIA PLUS P11 — GLOBAL_USER como escopo canônico",
    "",
    f"- Resultado: **{result['result']}**",
    f"- Schema: `{result['schema']}`",
    f"- Memory Scope: `{result['memory_scope_version']}`",
    f"- Legado classificado como GLOBAL_USER: `{result['legacy_backfill_count']}`",
    f"- Checks: `{sum(1 for x in checks.values() if x)}/{len(checks)}`",
    "",
    "## Separação canônica",
    "",
    "- `memory_scope = GLOBAL_USER|PROJECT|MISSION|SESSION` — contexto semântico.",
    "- `sharing_scope = PRIVATE_USER|PROJECT_SHARED|AGENT_PRIVATE|AGENT_TEAM|ORGANIZATION_SHARED|SYSTEM_SHARED` — ACL.",
    "- `Mem\u00f3ria Geral` permanece somente label humano de `GLOBAL_USER`.",
    "- O RLS continua baseado em `sharing_scope`; `memory_scope` não concede acesso.",
    "",
    "## Checks",
    "",
] + [f"- [{'x' if ok else ' '}] `{name}`" for name, ok in checks.items()]
md_bytes = ("\n".join(md_lines) + "\n").encode("utf-8")
(ROOT / "evidence" / "MEMORIA_PLUS_P11_PROOF.json").write_bytes(json_bytes)
(ROOT / "evidence" / "MEMORIA_PLUS_P11_PROOF.md").write_bytes(md_bytes)
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result["result"] == "PASS" else 1)
