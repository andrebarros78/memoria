from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0")
ADAPTER_ROOT = Path(r"C:\New Projet\MEMORIA-CLIENT-ADAPTER")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ADAPTER_ROOT / "src"))

from memoria_client_adapter import (  # noqa: E402
    MemoryClientAdapter,
    WindowsDpapiCredentialProvider,
)

from memory_permanent.ontology import (  # noqa: E402
    RELATION_RULES,
    TRANSITION_RULES,
    KnowledgeType,
)


def require(condition: object, detail: object = "proof assertion failed") -> None:
    if not condition:
        raise RuntimeError(f"proof requirement failed: {detail!r}")


BASE = "http://127.0.0.1:8787"
AUTH = Path(os.getenv("ProgramData", r"C:\ProgramData")) / "MemoriaPermanente" / "auth" / "clients" / "local-admin.dpapi"
client = MemoryClientAdapter(BASE, client_id="local-admin", credential_provider=WindowsDpapiCredentialProvider(AUTH))

raw = (ROOT / "runtime/secrets/pgpass.conf").read_text(encoding="ascii").strip()
host, port, dbname, user, password = raw.split(":", 4)
DSN = f"host={host} port={port} dbname={dbname} user={user} password={password} connect_timeout=5"


def raw_status(path: str) -> int:
    req = urllib.request.Request(BASE + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:  # nosec B310 -- URL base is a fixed loopback HTTP origin; scheme is not user-controlled.
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


def remember(category: str, key: str, marker: str) -> str:
    return client.remember(
        namespace="P07_PROOF",
        memory_key=key,
        category=category,
        content={"marker": marker, "category": category, "revision": 1},
        content_text=f"P07 ontology proof {category} {marker}",
        provenance={"proof": "MEMORIA_PLUS_P07", "marker": marker},
        confidence=0.9,
        source="p07-proof",
        source_version="P07-1",
        tags=["MEMORIA PLUS", "P07", category],
        sharing_scope="SYSTEM_SHARED",
        idempotency_key=f"p07-{key}",
    )


def current_version(item_id: str) -> dict:
    status, body = client.request("GET", f"/v1/memories/{item_id}/versions")
    require(status == 200, (status, body))
    return body["versions"][-1]


def sqlstate_for(sql: str, params: tuple = ()) -> str | None:
    conn = psycopg.connect(DSN, autocommit=True)
    try:
        conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',false)")
        try:
            with conn.transaction():
                conn.execute(sql, params)
        except psycopg.Error as exc:
            return str(exc.sqlstate or "")
        return None
    finally:
        conn.close()


suffix = uuid.uuid4().hex[:12]
marker = "P07_" + suffix.upper()

health = client.health()
unsigned_ontology = raw_status("/v1/ontology")
status, ontology_api = client.request("GET", "/v1/ontology")
require(status == 200, (status, ontology_api))

# API rejects free-text categories before persistence.
invalid_memory = {
    "namespace": "P07_PROOF",
    "memory_key": "invalid-category-" + suffix,
    "category": "MAGIC",
    "content": {"marker": marker},
    "content_text": marker,
    "provenance": {"proof": "P07_INVALID_CATEGORY"},
    "confidence": 1.0,
    "source": "p07-proof",
}
invalid_category_status, _ = client.request("POST", "/v1/memories", payload=invalid_memory)

# Valid canonical memories.
evidence_id = remember("EVIDENCE", "evidence-" + suffix, marker)
hypothesis_id = remember("HYPOTHESIS", "hypothesis-" + suffix, marker)
procedure_id = remember("PROCEDURE", "procedure-" + suffix, marker)

# Validate hypothesis first so the ontology transition must invalidate that validation.
hyp_v1 = current_version(hypothesis_id)
validation_payload = {
    "expected_version": int(hyp_v1["version_no"]),
    "expected_content_sha256": hyp_v1["content_sha256"],
    "status": "VALIDATED",
    "governor_eligible": False,
    "evidence": {"proof": "P07_PRE_TRANSITION_VALIDATION"},
}
status, validated = client.request("POST", f"/v1/memories/{hypothesis_id}/validation", payload=validation_payload)
require(status == 200 and validated['validation_status'] == 'VALIDATED', (status, validated))

# Valid relation: EVIDENCE SUPPORTS HYPOTHESIS.
valid_relation_payload = {
    "from_item_id": evidence_id,
    "relation_type": "SUPPORTS",
    "to_item_id": hypothesis_id,
    "provenance": {"proof": "P07_VALID_RELATION"},
    "confidence": 0.95,
}
status, relation1 = client.request("POST", "/v1/knowledge-relations", payload=valid_relation_payload)
require(status == 201, (status, relation1))
relation1_id = relation1["relation_id"]

# Invalid matrix relation: PROCEDURE CAUSES HYPOTHESIS.
invalid_relation_payload = {
    "from_item_id": procedure_id,
    "relation_type": "CAUSES",
    "to_item_id": hypothesis_id,
    "provenance": {"proof": "P07_INVALID_RELATION"},
    "confidence": 1.0,
}
invalid_relation_status, _ = client.request("POST", "/v1/knowledge-relations", payload=invalid_relation_payload)

# Valid ontology transition HYPOTHESIS -> FACT.
transition_payload = {
    "to_category": "FACT",
    "reason": "P07 prove explicit hypothesis promotion",
    "evidence": {"relation_id": relation1_id, "proof": "P07_TRANSITION"},
}
status, transition = client.request("POST", f"/v1/memories/{hypothesis_id}/ontology-transition", payload=transition_payload)
require(status == 200 and transition['from_category'] == 'HYPOTHESIS' and (transition['to_category'] == 'FACT'), (status, transition))

# The historical relation must be stale but retain its original category snapshots.
status, relation_view = client.request("GET", f"/v1/memories/{hypothesis_id}/knowledge-relations")
require(status == 200, (status, relation_view))
relation1_after = next(x for x in relation_view["relations"] if x["relation_id"] == relation1_id)

# Invalid reverse transition FACT -> HYPOTHESIS.
invalid_transition_payload = {"to_category": "HYPOTHESIS", "reason": "must fail", "evidence": {"proof": "P07_INVALID_TRANSITION"}}
invalid_transition_status, _ = client.request("POST", f"/v1/memories/{hypothesis_id}/ontology-transition", payload=invalid_transition_payload)

# New valid relation against FACT, then revise source to prove version-bound staleness.
relation2_payload = {
    "from_item_id": evidence_id,
    "relation_type": "SUPPORTS",
    "to_item_id": hypothesis_id,
    "provenance": {"proof": "P07_VERSION_BOUND_RELATION"},
    "confidence": 0.95,
}
status, relation2 = client.request("POST", "/v1/knowledge-relations", payload=relation2_payload)
require(status == 201, (status, relation2))
relation2_id = relation2["relation_id"]
evidence_v1 = current_version(evidence_id)
revision_payload = {
    "content": {"marker": marker, "category": "EVIDENCE", "revision": 2},
    "content_text": f"P07 ontology proof EVIDENCE {marker} revised V2",
    "provenance": {"proof": "P07_SOURCE_REVISION"},
    "confidence": 0.9,
    "source": "p07-proof",
    "source_version": "P07-2",
    "tags": ["MEMORIA PLUS", "P07", "EVIDENCE"],
    "expected_version": int(evidence_v1["version_no"]),
}
status, evidence_v2 = client.request("POST", f"/v1/memories/{evidence_id}/versions", payload=revision_payload, headers={"Idempotency-Key": "p07-revise-" + suffix})
require(status == 201, (status, evidence_v2))

# Direct schema bypass attempts.
direct_bad_category_state = sqlstate_for(
    """INSERT INTO memory_items(item_id,namespace,memory_key,category,content_json,content_text,provenance,confidence,source,content_sha256,tenant_id,sharing_scope,validation_status,governor_eligible)
       VALUES(%s,'P07_PROOF',%s,'MAGIC','{}'::jsonb,'bad','{}'::jsonb,1.0,'p07','0','LEGACY','SYSTEM_SHARED','UNVALIDATED',false)""",
    ("mem-bad-" + suffix, "bad-category-" + suffix),
)

evidence_current = current_version(evidence_id)
fact_current = current_version(hypothesis_id)
direct_bad_relation_state = sqlstate_for(
    """INSERT INTO memory_knowledge_relations(relation_id,tenant_id,from_item_id,from_version_id,from_category,relation_type,to_item_id,to_version_id,to_category,provenance,confidence,created_by)
       VALUES(%s,'LEGACY',%s,%s,'PROCEDURE','CAUSES',%s,%s,'FACT','{}'::jsonb,1.0,'p07-direct')""",
    ("rel-bad-" + suffix, procedure_id, current_version(procedure_id)["version_id"], hypothesis_id, fact_current["version_id"]),
)
direct_update_category_state = sqlstate_for("UPDATE memory_items SET category='EVIDENCE' WHERE item_id=%s", (hypothesis_id,))
direct_bad_transition_state = sqlstate_for(
    "SELECT memory_apply_ontology_transition(%s,%s,'HYPOTHESIS','p07-direct','must fail','{}'::jsonb)",
    ("trn-bad-" + suffix, hypothesis_id),
)
direct_rule_mutation_state = sqlstate_for(
    "UPDATE ontology_relation_rules SET ontology_version='MUTATED' WHERE source_category='EVIDENCE' AND relation_type='SUPPORTS' AND target_category='FACT'"
)

with psycopg.connect(DSN, row_factory=dict_row) as conn:
    conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',false)")
    schema = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()["value"]
    ontology_version = conn.execute("SELECT value FROM schema_meta WHERE key='ontology_version'").fetchone()["value"]
    categories = {r["category"] for r in conn.execute("SELECT DISTINCT category FROM memory_items").fetchall()}
    db_relation_rules = {
        (r["source_category"], r["relation_type"], r["target_category"])
        for r in conn.execute("SELECT source_category,relation_type,target_category FROM ontology_relation_rules").fetchall()
    }
    db_transition_rules = {
        (r["from_category"], r["to_category"])
        for r in conn.execute("SELECT from_category,to_category FROM ontology_transition_rules").fetchall()
    }
    legacy_counts = {
        r["from_category"]: int(r["n"])
        for r in conn.execute("SELECT from_category,count(*) n FROM ontology_legacy_category_migrations GROUP BY from_category ORDER BY from_category").fetchall()
    }
    rls_rows = conn.execute("""SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class
        WHERE relname IN ('ontology_legacy_category_migrations','memory_knowledge_relations','memory_knowledge_relation_events','memory_ontology_transitions') ORDER BY relname""").fetchall()
    relation_rows = conn.execute("SELECT relation_id,from_category,to_category,status,stale_reason FROM memory_knowledge_relations WHERE relation_id IN (%s,%s) ORDER BY relation_id", (relation1_id, relation2_id)).fetchall()
    relation_events = conn.execute("SELECT relation_id,old_status,new_status,reason FROM memory_knowledge_relation_events WHERE relation_id IN (%s,%s) ORDER BY seq", (relation1_id, relation2_id)).fetchall()
    transition_row = conn.execute("SELECT transition_id,from_category,to_category FROM memory_ontology_transitions WHERE transition_id=%s", (transition["transition_id"],)).fetchone()
    item_state = conn.execute("SELECT category,validation_status,governor_eligible FROM memory_items WHERE item_id=%s", (hypothesis_id,)).fetchone()
    constraints = [r["def"] for r in conn.execute("SELECT pg_get_constraintdef(oid) def FROM pg_constraint WHERE conname='memory_items_category_ontology_check'").fetchall()]

expected_types = {x.value for x in KnowledgeType}
py_relation_rules = {(a.value, b.value, c.value) for a, b, c in RELATION_RULES}
py_transition_rules = {(a.value, b.value) for a, b in TRANSITION_RULES}
rel_by_id = {r["relation_id"]: r for r in relation_rows}

checks = {
    "api_0_15_2": health.get("version") == "0.15.2",
    "ontology_requires_auth": unsigned_ontology == 401,
    "ontology_api_version": ontology_api.get("version") == "KO-1.0.0",
    "exact_15_types": set(ontology_api.get("knowledge_types") or []) == expected_types and len(expected_types) == 15,
    "invalid_category_api_422": invalid_category_status == 422,
    "valid_relation_api_201": bool(relation1_id),
    "invalid_relation_api_422": invalid_relation_status == 422,
    "valid_transition_api_200": transition.get("to_category") == "FACT",
    "invalid_transition_api_422": invalid_transition_status == 422,
    "relation_snapshot_preserved_after_transition": relation1_after["from_category"] == "EVIDENCE" and relation1_after["to_category"] == "HYPOTHESIS" and relation1_after["status"] == "STALE",
    "relation_stale_on_category_transition": rel_by_id[relation1_id]["status"] == "STALE" and rel_by_id[relation1_id]["stale_reason"] == "ONTOLOGY_CATEGORY_TRANSITION",
    "relation_stale_on_source_revision": rel_by_id[relation2_id]["status"] == "STALE" and rel_by_id[relation2_id]["stale_reason"] == "SOURCE_VERSION_SUPERSEDED",
    "transition_invalidates_validation": item_state["category"] == "FACT" and item_state["validation_status"] == "UNVALIDATED" and item_state["governor_eligible"] is False,
    "transition_ledger_exact": transition_row and transition_row["from_category"] == "HYPOTHESIS" and transition_row["to_category"] == "FACT",
    "relation_state_events_recorded": len(relation_events) >= 4,
    "schema_invalid_category_rejected": direct_bad_category_state == "23514",
    "schema_invalid_relation_rejected": direct_bad_relation_state == "23514",
    "schema_direct_category_update_rejected": direct_update_category_state == "42501",
    "schema_invalid_transition_rejected": direct_bad_transition_state == "23514",
    "ontology_rules_immutable": direct_rule_mutation_state == "42501",
    "domain_db_relation_rules_identical": db_relation_rules == py_relation_rules and len(db_relation_rules) == 96,
    "domain_db_transition_rules_identical": db_transition_rules == py_transition_rules and len(db_transition_rules) == 7,
    "legacy_categories_migrated": legacy_counts == {"DOCUMENT": 4, "EVENT": 586, "REQUIREMENT": 19, "RULE": 7, "STATE": 1},
    "all_persisted_categories_canonical": categories.issubset(expected_types),
    "category_check_constraint_present": len(constraints) == 1 and "FACT" in constraints[0] and "OBJECTIVE" in constraints[0],
    "ontology_tables_force_rls": len(rls_rows) == 4 and all(r["relrowsecurity"] and r["relforcerowsecurity"] for r in rls_rows),
    "schema_version": schema == "memory-0.15.2",
    "ontology_schema_version": ontology_version == "KO-1.0.0",
}
failed = [k for k, v in checks.items() if not v]
proof = {
    "generated_at": datetime.now(UTC).isoformat(),
    "tag": "MEMORIA PLUS",
    "priority": 7,
    "title": "Ontologia formal de conhecimento",
    "result": "PASS" if not failed else "FAIL",
    "failed": failed,
    "checks": checks,
    "api": {"version": health.get("version"), "unsigned_ontology": unsigned_ontology, "invalid_category": invalid_category_status, "invalid_relation": invalid_relation_status, "invalid_transition": invalid_transition_status},
    "ontology": {"version": ontology_version, "knowledge_types": sorted(expected_types), "relation_rule_count": len(db_relation_rules), "transition_rule_count": len(db_transition_rules)},
    "legacy_migration_counts": legacy_counts,
    "relation_proof": {"relation1": dict(rel_by_id[relation1_id]), "relation2": dict(rel_by_id[relation2_id]), "event_count": len(relation_events)},
    "transition_proof": dict(transition_row) if transition_row else None,
    "schema_rejection_sqlstates": {"invalid_category": direct_bad_category_state, "invalid_relation": direct_bad_relation_state, "direct_category_update": direct_update_category_state, "invalid_transition": direct_bad_transition_state, "rule_mutation": direct_rule_mutation_state},
    "schema": schema,
}
EV = ROOT / "evidence"
EV.mkdir(exist_ok=True)
(EV / "MEMORIA_PLUS_P07_PROOF.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
lines = [
    "# MEMORIA PLUS P07 PROOF", "", f"**Result:** {proof['result']}", "",
    f"- API: {health.get('version')}", f"- Schema: {schema}", f"- Ontology: {ontology_version}",
    f"- Knowledge types: {len(expected_types)}", f"- Relation rules: {len(db_relation_rules)}", f"- Transition rules: {len(db_transition_rules)}",
    f"- Legacy rows normalized with ledger: {sum(legacy_counts.values())}", "", "## Checks",
] + [f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in checks.items()]
(EV / "MEMORIA_PLUS_P07_PROOF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(json.dumps({"result": proof["result"], "failed": failed, "checks": checks, "schema": schema, "ontology": ontology_version}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not failed else 1)
