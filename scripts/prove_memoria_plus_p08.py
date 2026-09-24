from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

ROOT = Path(r"C:\New Projet\MEMORIA-PERMANENTE")
ADAPTER_ROOT = Path(r"C:\New Projet\MEMORIA-CLIENT-ADAPTER")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ADAPTER_ROOT / "src"))

from memoria_client_adapter import (  # noqa: E402
    MemoryAuthorizationError,
    MemoryClientAdapter,
    WindowsDpapiCredentialProvider,
)

from memory_permanent.experience_graph import (  # noqa: E402
    EDGE_RULES,
    EXPERIENCE_GRAPH_VERSION,
    ExperienceNodeType,
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


def current_version(item_id: str) -> dict:
    status, body = client.request("GET", f"/v1/memories/{item_id}/versions")
    require(status == 200 and body.get('versions'), (status, body))
    return body["versions"][-1]


def remember(category: str, key: str, marker: str) -> tuple[str, dict]:
    item_id = client.remember(
        namespace="P08_PROOF",
        memory_key=key,
        category=category,
        content={"marker": marker, "category": category, "revision": 1},
        content_text=f"P08 complete experience graph proof {category} {marker}",
        provenance={"proof": "MEMORIA_PLUS_P08", "marker": marker},
        confidence=0.95,
        source="p08-proof",
        source_version="P08-1",
        tags=["MEMORIA PLUS", "P08", category],
        sharing_scope="SYSTEM_SHARED",
        idempotency_key=f"p08-memory-{key}",
    )
    return item_id, current_version(item_id)


def create_node(mission: str, node_type: str, entity_ref: str, occurred_at: datetime, memory_item_id: str | None = None, memory_version_id: str | None = None):
    payload = {
        "node_type": node_type,
        "entity_ref": entity_ref,
        "payload": {"proof": "MEMORIA_PLUS_P08", "entity_ref": entity_ref},
        "provenance": {"proof": "MEMORIA_PLUS_P08"},
        "memory_item_id": memory_item_id,
        "memory_version_id": memory_version_id,
        "occurred_at": occurred_at.isoformat(),
    }
    return client.request("POST", f"/v1/experience/missions/{mission}/nodes", payload=payload)


def create_edge(mission: str, source: str, relation: str, target: str, occurred_at: datetime):
    return client.request(
        "POST",
        f"/v1/experience/missions/{mission}/edges",
        payload={
            "from_node_id": source,
            "relation_type": relation,
            "to_node_id": target,
            "evidence": {"proof": "MEMORIA_PLUS_P08"},
            "occurred_at": occurred_at.isoformat(),
        },
    )


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
marker = "P08_" + suffix.upper()
mission = "P08-MISSION-" + suffix.upper()
mission_other = mission + "-OTHER"
base_time = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)

health = client.health()
unsigned_spec = raw_status("/v1/experience/spec")
status, spec = client.request("GET", "/v1/experience/spec")
require(status == 200, (status, spec))

memory_specs = [
    ("HYPOTHESIS", "hypothesis"),
    ("EVIDENCE", "evidence"),
    ("DECISION", "decision"),
    ("INTERVENTION", "intervention"),
    ("OUTCOME", "result"),
    ("LEARNING", "learning"),
    ("FACT", "knowledge"),
]
memories: dict[str, dict] = {}
for category, label in memory_specs:
    item_id, version = remember(category, f"{label}-{suffix}", marker)
    memories[label] = {"item_id": item_id, "version": version}

node_specs = [
    ("HYPOTHESIS", "hypothesis", 1),
    ("EVIDENCE", "evidence", 2),
    ("DECISION", "decision", 3),
    ("INTERVENTION", "intervention", 4),
    ("RESULT", "result", 5),
    ("LEARNING", "learning", 6),
    ("KNOWLEDGE", "knowledge", 7),
]
nodes: dict[str, dict] = {}
for node_type, label, second in node_specs:
    mem = memories[label]
    status, body = create_node(
        mission,
        node_type,
        f"{label}-{suffix}",
        base_time + timedelta(seconds=second),
        mem["item_id"],
        mem["version"]["version_id"],
    )
    require(status == 201, (node_type, status, body))
    nodes[label] = body

edge_specs = [
    ("hypothesis", "EVALUATED_BY", "evidence", 8),
    ("evidence", "INFORMS", "decision", 9),
    ("decision", "IMPLEMENTED_BY", "intervention", 10),
    ("intervention", "PRODUCES", "result", 11),
    ("result", "DERIVES", "learning", 12),
    ("learning", "CONSOLIDATES", "knowledge", 13),
]
edges: list[dict] = []
for source, relation, target, second in edge_specs:
    status, body = create_edge(mission, nodes[source]["node_id"], relation, nodes[target]["node_id"], base_time + timedelta(seconds=second))
    require(status == 201, (source, relation, target, status, body))
    edges.append(body)

status, graph_before = client.request("GET", f"/v1/experience/missions/{mission}/graph")
require(status == 200, (status, graph_before))
require(graph_before['reconstruction']['reconstruction_status'] == 'COMPLETE', graph_before)

# Domain/API rejection: wrong memory-category binding for RESULT.
status_invalid_binding, invalid_binding = create_node(
    mission,
    "RESULT",
    f"invalid-result-{suffix}",
    base_time + timedelta(seconds=14),
    memories["knowledge"]["item_id"],
    memories["knowledge"]["version"]["version_id"],
)

# Domain/API rejection: relation type exists but is invalid for these endpoint node types.
status_invalid_relation, invalid_relation = create_edge(
    mission,
    nodes["hypothesis"]["node_id"],
    "PRODUCES",
    nodes["result"]["node_id"],
    base_time + timedelta(seconds=15),
)

# Cross-mission scope rejection.
status, other_evidence = create_node(mission_other, "EVIDENCE", f"other-evidence-{suffix}", base_time + timedelta(seconds=16))
require(status == 201, (status, other_evidence))
try:
    status_cross_mission, cross_mission = create_edge(
        mission,
        nodes["hypothesis"]["node_id"],
        "EVALUATED_BY",
        other_evidence["node_id"],
        base_time + timedelta(seconds=17),
    )
except MemoryAuthorizationError as exc:
    status_cross_mission, cross_mission = 403, str(exc)

# Temporal rejection using a valid edge rule but target event earlier than source event.
status, late_h = create_node(mission, "HYPOTHESIS", f"late-h-{suffix}", base_time + timedelta(seconds=30))
require(status == 201, (status, late_h))
status, early_e = create_node(mission, "EVIDENCE", f"early-e-{suffix}", base_time + timedelta(seconds=20))
require(status == 201, (status, early_e))
status_temporal, temporal_body = create_edge(
    mission, late_h["node_id"], "EVALUATED_BY", early_e["node_id"], base_time + timedelta(seconds=31)
)

# Preserve historical semantics after the bound HYPOTHESIS changes ontology type.
status, transition = client.request(
    "POST",
    f"/v1/memories/{memories['hypothesis']['item_id']}/ontology-transition",
    payload={
        "to_category": "FACT",
        "reason": "P08 historical snapshot proof",
        "evidence": {"proof": "MEMORIA_PLUS_P08"},
    },
)
require(status == 200, (status, transition))
status, graph_after = client.request("GET", f"/v1/experience/missions/{mission}/graph")
require(status == 200, (status, graph_after))
h_node_after = next(x for x in graph_after["nodes"] if x["node_id"] == nodes["hypothesis"]["node_id"])

# Direct schema-level fail-closed checks.
invalid_relation_sqlstate = sqlstate_for(
    "INSERT INTO experience_graph_edges(graph_edge_id,tenant_id,mission_id,from_node_id,relation_type,to_node_id,evidence,occurred_at,created_by) VALUES(%s,%s,%s,%s,'PRODUCES',%s,'{}'::jsonb,%s,'p08-proof')",
    (f"ege-invalid-{suffix}", "LEGACY", mission, nodes["hypothesis"]["node_id"], nodes["result"]["node_id"], base_time + timedelta(seconds=40)),
)
temporal_sqlstate = sqlstate_for(
    "INSERT INTO experience_graph_edges(graph_edge_id,tenant_id,mission_id,from_node_id,relation_type,to_node_id,evidence,occurred_at,created_by) VALUES(%s,%s,%s,%s,'EVALUATED_BY',%s,'{}'::jsonb,%s,'p08-proof')",
    (f"ege-time-{suffix}", "LEGACY", mission, late_h["node_id"], early_e["node_id"], base_time + timedelta(seconds=41)),
)
node_update_sqlstate = sqlstate_for("UPDATE experience_graph_nodes SET entity_ref=entity_ref||'-x' WHERE node_id=%s", (nodes["decision"]["node_id"],))
edge_delete_sqlstate = sqlstate_for("DELETE FROM experience_graph_edges WHERE graph_edge_id=%s", (edges[0]["graph_edge_id"],))
rule_mutation_sqlstate = sqlstate_for(
    "INSERT INTO experience_graph_relation_rules(source_type,relation_type,target_type) VALUES('HYPOTHESIS','PRODUCES','RESULT')"
)

with psycopg.connect(DSN, autocommit=True) as conn:
    conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',false)")
    schema = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
    graph_version = conn.execute("SELECT value FROM schema_meta WHERE key='experience_graph_version'").fetchone()[0]
    db_rules = conn.execute("SELECT source_type,relation_type,target_type FROM experience_graph_relation_rules ORDER BY 1,2,3").fetchall()
    rls = conn.execute(
        "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname IN ('experience_graph_nodes','experience_graph_edges') ORDER BY relname"
    ).fetchall()
    legacy_edge_count = conn.execute("SELECT count(*) FROM memory_experience_edges").fetchone()[0]
    audit_counts = conn.execute(
        "SELECT event_type,count(*) FROM audit_events WHERE event_type IN ('EXPERIENCE_GRAPH_NODE_CREATED','EXPERIENCE_GRAPH_EDGE_CREATED') GROUP BY event_type ORDER BY event_type"
    ).fetchall()
    system_visible = conn.execute("SELECT count(*) FROM experience_graph_nodes WHERE mission_id=%s", (mission,)).fetchone()[0]
    conn.execute("SELECT set_config('app.current_tenant','P08_OTHER_TENANT',false)")
    other_tenant_visible = conn.execute("SELECT count(*) FROM experience_graph_nodes WHERE mission_id=%s", (mission,)).fetchone()[0]

expected_rules = sorted((a.value, b.value, c.value) for a, b, c in EDGE_RULES)
actual_rules = sorted(tuple(x) for x in db_rules)
expected_order = [nodes[label]["node_id"] for _, label, _ in node_specs]

checks = {
    "api_0_16_1": health.get("version") == "0.16.1",
    "spec_requires_auth": unsigned_spec == 401,
    "graph_spec_version": spec.get("version") == EXPERIENCE_GRAPH_VERSION == "EG-1.0.0",
    "exact_first_class_types": set(spec.get("node_types") or []) == {x.value for x in ExperienceNodeType},
    "exact_7_causal_rules": len(spec.get("edge_rules") or []) == 7 and actual_rules == expected_rules,
    "seven_bound_first_class_nodes_created": len(nodes) == 7 and all(x.get("memory_version_id") for x in nodes.values()),
    "complete_graph_has_7_bound_nodes": len(graph_before["nodes"]) == 7,
    "complete_graph_has_6_chain_edges": len(graph_before["edges"]) == 6,
    "mission_reconstruction_complete": graph_before["reconstruction"]["reconstruction_status"] == "COMPLETE",
    "causal_order_exact": graph_before["reconstruction"]["causal_order"] == expected_order,
    "timeline_exact": graph_before["reconstruction"]["timeline"] == expected_order,
    "invalid_memory_binding_api_422": status_invalid_binding == 422,
    "invalid_relation_api_422": status_invalid_relation == 422,
    "cross_mission_edge_api_403": status_cross_mission == 403,
    "temporal_violation_api_422": status_temporal == 422,
    "historical_category_snapshot_preserved": h_node_after["memory_category_snapshot"] == "HYPOTHESIS",
    "historical_version_snapshot_preserved": h_node_after["memory_version_id"] == memories["hypothesis"]["version"]["version_id"],
    "reconstruction_survives_source_transition": graph_after["reconstruction"]["reconstruction_status"] == "COMPLETE",
    "schema_invalid_relation_rejected": invalid_relation_sqlstate == "23514",
    "schema_temporal_violation_rejected": temporal_sqlstate == "23514",
    "nodes_append_only": node_update_sqlstate == "55000",
    "edges_append_only": edge_delete_sqlstate == "55000",
    "causal_rules_immutable": rule_mutation_sqlstate == "42501",
    "experience_tables_force_rls": len(rls) == 2 and all(bool(row[1]) and bool(row[2]) for row in rls),
    "tenant_isolation_proven": system_visible >= 7 and other_tenant_visible == 0,
    "legacy_experience_graph_preserved": int(legacy_edge_count) >= 31,
    "audit_events_recorded": dict(audit_counts).get("EXPERIENCE_GRAPH_NODE_CREATED", 0) >= 10 and dict(audit_counts).get("EXPERIENCE_GRAPH_EDGE_CREATED", 0) >= 6,
    "schema_version": schema == "memory-0.16.1",
    "experience_graph_schema_version": graph_version == "EG-1.0.0",
}
failed = [name for name, passed in checks.items() if not passed]
result = {
    "generated_at": datetime.now(UTC).isoformat(),
    "tag": "MEMORIA PLUS",
    "priority": 8,
    "title": "Experience Graph completo",
    "result": "PASS" if not failed else "FAIL",
    "failed": failed,
    "checks": checks,
    "api": {
        "version": health.get("version"),
        "unsigned_spec": unsigned_spec,
        "invalid_binding": status_invalid_binding,
        "invalid_relation": status_invalid_relation,
        "cross_mission": status_cross_mission,
        "temporal_violation": status_temporal,
    },
    "schema": schema,
    "experience_graph_version": graph_version,
    "mission_id": mission,
    "first_class_node_ids": {label: body["node_id"] for label, body in nodes.items()},
    "causal_order": graph_before["reconstruction"]["causal_order"],
    "timeline": graph_before["reconstruction"]["timeline"],
    "historical_snapshot": {
        "node_id": h_node_after["node_id"],
        "memory_item_id": h_node_after["memory_item_id"],
        "memory_version_id": h_node_after["memory_version_id"],
        "memory_content_sha256": h_node_after["memory_content_sha256"],
        "memory_category_snapshot": h_node_after["memory_category_snapshot"],
        "current_item_transition": transition,
    },
    "schema_rejection_sqlstates": {
        "invalid_relation": invalid_relation_sqlstate,
        "temporal_violation": temporal_sqlstate,
        "node_update": node_update_sqlstate,
        "edge_delete": edge_delete_sqlstate,
        "rule_mutation": rule_mutation_sqlstate,
    },
    "rls": [list(x) for x in rls],
    "legacy_edge_count": int(legacy_edge_count),
    "audit_counts": {str(k): int(v) for k, v in audit_counts},
}

json_path = ROOT / "evidence/MEMORIA_PLUS_P08_PROOF.json"
md_path = ROOT / "evidence/MEMORIA_PLUS_P08_PROOF.md"
json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
md_lines = [
    "# MEMORIA PLUS — Prioridade 08 — Prova",
    "",
    f"- Resultado: **{result['result']}**",
    f"- API: `{health.get('version')}`",
    f"- Schema: `{schema}`",
    f"- Experience Graph: `{graph_version}`",
    f"- Missão de prova: `{mission}`",
    f"- Entidades first-class: `{len(nodes)}`",
    f"- Arestas da cadeia causal: `{len(edges)}`",
    f"- Reconstrução: `{graph_before['reconstruction']['reconstruction_status']}`",
    "",
    "## Checks",
]
md_lines += [f"- {name}: {'PASS' if passed else 'FAIL'}" for name, passed in checks.items()]
md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
print(json.dumps({"result": result["result"], "failed": failed, "checks": checks, "schema": schema, "experience_graph_version": graph_version}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not failed else 1)
