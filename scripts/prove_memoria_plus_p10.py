from __future__ import annotations

import hashlib
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
    MemoryClientAdapter,
    WindowsDpapiCredentialProvider,
)

from memory_permanent.decision_memory import (  # noqa: E402
    DECISION_RECORD_VERSION,
    decision_core_material,
    sha256_json,
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
    st, body = client.request("GET", f"/v1/memories/{item_id}/versions")
    require(st == 200 and body.get('versions'), (st, body))
    return body["versions"][-1]


def sqlstate(sql: str, params: tuple = ()) -> str | None:
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',false)")
        try:
            with conn.transaction():
                conn.execute(sql, params)
        except psycopg.Error as exc:
            return str(exc.sqlstate or "")
        return None


suffix = uuid.uuid4().hex[:12].upper()
mission = f"P10-MISSION-{suffix}"
namespace = f"P10_PROOF_{suffix}"
now = datetime.now(UTC).replace(microsecond=0)

health = client.health()
unsigned_spec = raw_status("/v1/decision-record-spec")
st, spec = client.request("GET", "/v1/decision-record-spec")
require(st == 200, (st, spec))

# Sovereign mission anchor.
st, checkpoint = client.request("POST", "/v1/checkpoints", payload={
    "namespace": namespace,
    "mission_id": mission,
    "step_index": 10,
    "state": {"phase": "P10_DECISION_PROOF", "marker": suffix, "ready": True},
    "checkpoint_id": f"cp-p10-{suffix.lower()}",
    "project_id": "MEMORIA-PERMANENTE",
})
require(st == 201, (st, checkpoint))

# Evidence memory bound to an exact version/hash.
evidence_item = client.remember(
    namespace=namespace,
    memory_key=f"decision-evidence-{suffix.lower()}",
    category="EVIDENCE",
    content={"finding": "formal decision evidence", "marker": suffix, "revision": 1},
    content_text=f"P10 formal sovereign decision evidence {suffix}",
    provenance={"proof": "MEMORIA_PLUS_P10", "marker": suffix},
    confidence=0.98,
    source="p10-proof",
    source_version="P10-1",
    tags=["MEMORIA PLUS", "P10", "DECISION_EVIDENCE"],
    sharing_scope="SYSTEM_SHARED",
    idempotency_key=f"p10-evidence-{suffix.lower()}",
)
ev_v1 = current_version(evidence_item)

critical_payload = {
    "mission_id": mission,
    "criticality": "CRITICAL",
    "objective": "Choose and preserve the safest formal action for P10 proof.",
    "context": {"marker": suffix, "risk": "high", "constraints": ["append-only", "version-bound evidence"]},
    "alternatives": [
        {"id": "A", "label": "Apply formal sovereign decision", "risk": "controlled"},
        {"id": "B", "label": "Keep textual decision reference", "risk": "unacceptable"},
    ],
    "rationale": "Alternative A is selected because it is bound to evidence, authority, mission state and replay proof.",
    "action": {"type": "APPLY_POLICY", "target": "MEMORIA-PERMANENTE", "parameters": {"policy": "FORMAL_DECISION", "marker": suffix}},
    "expected_outcome": {"formal_record": True, "replayable": True, "explainable": True},
    "proof": {"proof_id": f"P10-{suffix}", "kind": "END_TO_END"},
    "evidence_refs": [{"item_id": evidence_item, "version_id": ev_v1["version_id"], "role": "PRIMARY_EVIDENCE"}],
    "occurred_at": (now + timedelta(seconds=2)).isoformat(),
}

# Critical-policy rejection cases.
weak_alt = {**critical_payload, "alternatives": [critical_payload["alternatives"][0]]}
st_weak_alt, weak_alt_body = client.request("POST", "/v1/decisions", payload=weak_alt)
weak_ev = {**critical_payload, "evidence_refs": []}
st_weak_ev, weak_ev_body = client.request("POST", "/v1/decisions", payload=weak_ev)
caller_authority = {**critical_payload, "authority": {"client_id": "forged", "authority_tier": "ADMIN"}}
st_authority, authority_body = client.request("POST", "/v1/decisions", payload=caller_authority)

st, created = client.request("POST", "/v1/decisions", payload=critical_payload)
require(st == 201, (st, created))
decision_id = created["decision_id"]

st, bundle_before = client.request("GET", f"/v1/decisions/{decision_id}")
require(st == 200, (st, bundle_before))
decision = bundle_before["decision"]
recomputed_core = sha256_json(decision_core_material(
    mission_id=decision["mission_id"], mission_anchor_type=decision["mission_anchor_type"], mission_anchor_id=decision["mission_anchor_id"],
    mission_snapshot=decision["mission_snapshot"], criticality=decision["criticality"], objective=decision["objective"],
    context=decision["decision_context"], alternatives=decision["alternatives"], rationale=decision["rationale"], authority=decision["authority"],
    action=decision["action"], expected_outcome=decision["expected_outcome"], proof=decision["decision_proof"], occurred_at=decision["occurred_at"],
))

# New applications must reference a formal decision with matching mission.
st_bad_app, bad_app = client.request("POST", f"/v1/experience/applications?item_id={evidence_item}", payload={
    "action_ref": "p10-bogus-decision", "mission_id": mission, "decision_id": f"legacy-text-{suffix}", "context": {"proof": "P10"}
})
st_app, application = client.request("POST", f"/v1/experience/applications?item_id={evidence_item}", payload={
    "action_ref": "p10-formal-decision", "mission_id": mission, "decision_id": decision_id, "context": {"proof": "P10", "marker": suffix}
})
require(st_app == 201, (st_app, application))

# Historical evidence snapshot must survive later source revision.
st_rev, revised = client.request("POST", f"/v1/memories/{evidence_item}/versions", payload={
    "content": {"finding": "formal decision evidence revised after decision", "marker": suffix, "revision": 2},
    "content_text": f"P10 evidence revised after formal decision {suffix}",
    "provenance": {"proof": "MEMORIA_PLUS_P10", "revision": 2},
    "confidence": 0.99,
    "source": "p10-proof",
    "source_version": "P10-2",
    "tags": ["MEMORIA PLUS", "P10", "DECISION_EVIDENCE", "REVISED"],
    "changed_by": "p10-proof",
    "expected_version": 1,
})
require(st_rev == 201, (st_rev, revised))
ev_v2 = current_version(evidence_item)
st, bundle_after_revision = client.request("GET", f"/v1/decisions/{decision_id}")
require(st == 200, 'prove_memoria_plus_p10.py:166')
bound_ev = bundle_after_revision["explanation"]["evidence_used"][0]

# Actual outcome cannot predate decision.
st_early, early_body = client.request("POST", f"/v1/decisions/{decision_id}/outcomes", payload={
    "success": True, "actual_outcome": {"formal_record": True}, "proof": {"proof": "too-early"},
    "occurred_at": (now - timedelta(seconds=10)).isoformat(),
})
st_out, outcome = client.request("POST", f"/v1/decisions/{decision_id}/outcomes", payload={
    "success": True,
    "actual_outcome": {"formal_record": True, "replayable": True, "explainable": True, "application_id": application["application_id"]},
    "proof": {"proof": "MEMORIA_PLUS_P10", "application_id": application["application_id"]},
    "occurred_at": (now + timedelta(seconds=20)).isoformat(),
})
require(st_out == 201, (st_out, outcome))

st, bundle_final = client.request("GET", f"/v1/decisions/{decision_id}")
require(st == 200, 'prove_memoria_plus_p10.py:183')
st, replay_get = client.request("GET", f"/v1/decisions/{decision_id}/replay-package")
require(st == 200, 'prove_memoria_plus_p10.py:185')
st_r1, replay1 = client.request("POST", f"/v1/decisions/{decision_id}/replays", payload={"reason": "P10 deterministic replay proof 1"})
st_r2, replay2 = client.request("POST", f"/v1/decisions/{decision_id}/replays", payload={"reason": "P10 deterministic replay proof 2"})
require(st_r1 == 201 and st_r2 == 201, (st_r1, replay1, st_r2, replay2))

# Schema defenses.
direct_decision_state = sqlstate("""INSERT INTO sovereign_decisions(decision_id,tenant_id,mission_id,mission_anchor_type,mission_anchor_id,mission_snapshot,criticality,objective,decision_context,alternatives,rationale,authority,action,expected_outcome,decision_proof,core_sha256,occurred_at,created_by) VALUES(%s,'LEGACY',%s,'CHECKPOINT','x','{}'::jsonb,'NORMAL','x','{}'::jsonb,'[{\"id\":\"a\",\"label\":\"A\"}]'::jsonb,'r','{\"client_id\":\"x\"}'::jsonb,'{\"type\":\"x\",\"target\":\"x\"}'::jsonb,'{\"ok\":true}'::jsonb,'{\"p\":1}'::jsonb,%s,now(),'sql')""", (f"dec-direct-{suffix.lower()}", mission, "0"*64))
append_decision_state = sqlstate("UPDATE sovereign_decisions SET rationale='tamper' WHERE decision_id=%s", (decision_id,))
append_outcome_state = sqlstate("UPDATE sovereign_decision_outcomes SET success=false WHERE decision_id=%s", (decision_id,))

with psycopg.connect(DSN) as conn:
    conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',false)")
    meta = dict(conn.execute("SELECT key,value FROM schema_meta WHERE key IN ('schema_version','decision_record_version')").fetchall())
    rls = conn.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relkind='r' AND relname LIKE 'sovereign_decision%' ORDER BY relname").fetchall()
    guards = conn.execute("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname='trg_require_decision_context'").fetchone()[0]
    legacy_count = conn.execute("SELECT count(*) FROM sovereign_decision_legacy_inventory").fetchone()[0]
    audit_counts = dict(conn.execute("SELECT event_type,count(*) FROM audit_events WHERE event_type LIKE 'SOVEREIGN_DECISION%' GROUP BY event_type").fetchall())
    ledger = dict(conn.execute("SELECT version,checksum_sha256 FROM schema_migrations WHERE version IN ('0024_formal_sovereign_decisions','0025_harden_sovereign_decisions')").fetchall())

m24 = hashlib.sha256((ROOT/'migrations/0024_formal_sovereign_decisions.sql').read_bytes()).hexdigest()
m25 = hashlib.sha256((ROOT/'migrations/0025_harden_sovereign_decisions.sql').read_bytes()).hexdigest()
explanation = bundle_final["explanation"]
replay = bundle_final["replay_package"]
checks = {
    "api_0_18_1": health.get("version") == "0.18.1",
    "spec_requires_auth": unsigned_spec == 401,
    "decision_record_version": spec.get("version") == "DR-1.1.0" == DECISION_RECORD_VERSION,
    "critical_requires_two_alternatives": st_weak_alt == 422,
    "critical_requires_evidence": st_weak_ev == 422,
    "caller_cannot_assert_authority": st_authority == 422,
    "critical_decision_created": created.get("criticality") == "CRITICAL",
    "mission_anchor_checkpoint": decision.get("mission_anchor_type") == "CHECKPOINT" and decision.get("mission_anchor_id") == checkpoint.get("checkpoint_id"),
    "authority_derived": decision.get("authority",{}).get("client_id") == "local-admin" and decision.get("authority",{}).get("client_id") != "forged",
    "core_sha256_exact": recomputed_core == decision.get("core_sha256") == created.get("core_sha256"),
    "explanation_complete": all(k in explanation for k in ["objective","context","alternatives","evidence_used","rationale","authority","action","expected_outcome","actual_outcomes","proof","mission_snapshot"]),
    "legacy_textual_decision_rejected_for_new_application": st_bad_app == 422,
    "formal_decision_application_created": st_app == 201,
    "evidence_version_snapshot_preserved": bound_ev.get("version_id") == ev_v1.get("version_id") and bound_ev.get("content_sha256") == ev_v1.get("content_sha256") and ev_v2.get("version_id") != ev_v1.get("version_id"),
    "evidence_content_snapshot_preserved": bound_ev.get("evidence_snapshot",{}).get("content_json",{}).get("revision") == 1,
    "early_actual_outcome_rejected": st_early == 422,
    "actual_outcome_recorded": st_out == 201 and len(explanation.get("actual_outcomes",[])) == 1,
    "replay_contains_actual_outcome": len(replay.get("actual_outcomes",[])) == 1 and replay["actual_outcomes"][0]["actual_outcome"].get("formal_record") is True,
    "replay_contains_action": replay.get("action") == decision.get("action"),
    "replay_contains_mission_snapshot": replay.get("mission_snapshot") == decision.get("mission_snapshot"),
    "replay_get_matches_bundle": replay_get.get("replay_sha256") == replay.get("replay_sha256"),
    "materialized_replays_deterministic": replay1.get("replay_sha256") == replay2.get("replay_sha256") == replay.get("replay_sha256"),
    "replay_no_side_effect_mode": replay1.get("execution_mode") == "MATERIALIZED_NO_SIDE_EFFECT",
    "direct_decision_insert_rejected": direct_decision_state == "42501",
    "decision_append_only": append_decision_state == "55000",
    "outcome_append_only": append_outcome_state == "55000",
    "four_canonical_insert_guards": int(guards) == 4,
    "decision_tables_force_rls": len(rls) >= 5 and all(bool(x[1]) and bool(x[2]) for x in rls),
    "legacy_decisions_inventoried": int(legacy_count) >= 8,
    "decision_audit_events_recorded": int(audit_counts.get("SOVEREIGN_DECISION_RECORDED",0)) >= 1 and int(audit_counts.get("SOVEREIGN_DECISION_OUTCOME_RECORDED",0)) >= 1 and int(audit_counts.get("SOVEREIGN_DECISION_REPLAY_MATERIALIZED",0)) >= 2,
    "schema_version": meta.get("schema_version") == "memory-0.18.1",
    "decision_schema_version": meta.get("decision_record_version") == "DR-1.1.0",
    "migration_0024_exact": ledger.get("0024_formal_sovereign_decisions") == m24,
    "migration_0025_exact": ledger.get("0025_harden_sovereign_decisions") == m25,
}
failed=[k for k,v in checks.items() if not v]
result={
    "generated_at": datetime.now(UTC).isoformat(), "tag":"MEMORIA PLUS", "priority":10,
    "title":"Memoria de decisoes e missoes formal", "result":"PASS" if not failed else "FAIL", "failed":failed,
    "checks":checks, "schema":meta.get("schema_version"), "decision_record_version":meta.get("decision_record_version"),
    "decision_id":decision_id, "mission_id":mission, "core_sha256":decision.get("core_sha256"), "replay_sha256":replay.get("replay_sha256"),
    "evidence_binding":{"item_id":evidence_item,"version_id":bound_ev.get("version_id"),"content_sha256":bound_ev.get("content_sha256")},
    "actual_outcome_id": outcome.get("decision_outcome_id"), "application_id":application.get("application_id"),
    "sqlstates":{"direct_insert":direct_decision_state,"decision_update":append_decision_state,"outcome_update":append_outcome_state},
    "audit_counts":audit_counts,"legacy_inventory_count":int(legacy_count),
    "migrations":{"0024":m24,"0025":m25},
}
(ROOT/'evidence/MEMORIA_PLUS_P10_PROOF.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
lines=["# MEMORIA PLUS P10 — Prova tecnica","",f"- Resultado: **{result['result']}**",f"- API/schema: `0.18.1 / {result['schema']}`",f"- Decision Record: `{result['decision_record_version']}`",f"- Decisao: `{decision_id}`",f"- Core SHA-256: `{result['core_sha256']}`",f"- Replay SHA-256: `{result['replay_sha256']}`","","## Checks"]
lines += [f"- {k}: {'PASS' if v else 'FAIL'}" for k,v in checks.items()]
(ROOT/'evidence/MEMORIA_PLUS_P10_PROOF.md').write_text("\n".join(lines),encoding='utf-8')
print(json.dumps({"result":result["result"],"failed":failed,"checks":checks,"schema":result["schema"],"decision_record_version":result["decision_record_version"],"decision_id":decision_id,"replay_sha256":result["replay_sha256"]},ensure_ascii=False,indent=2))
raise SystemExit(0 if not failed else 1)
