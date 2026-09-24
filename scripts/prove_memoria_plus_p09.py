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

ROOT = Path(r"C:\New Projet\MEMORIA-PERMANENTE")
ADAPTER_ROOT = Path(r"C:\New Projet\MEMORIA-CLIENT-ADAPTER")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ADAPTER_ROOT / "src"))

from memoria_client_adapter import (  # noqa: E402
    MemoryClientAdapter,
    WindowsDpapiCredentialProvider,
)

from memory_permanent.causal_policy import (  # noqa: E402
    CAUSAL_POLICY_VERSION,
    causal_policy_spec,
    evaluate_causal_assessment,
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


def remember_correlation(key: str, marker: str) -> str:
    return client.remember(
        namespace="P09_PROOF",
        memory_key=key,
        category="CORRELATION",
        content={"marker": marker, "claim": "X correlates with Y"},
        content_text=f"P09 causal policy proof correlation {marker}",
        provenance={"proof": "MEMORIA_PLUS_P09", "marker": marker},
        confidence=0.75,
        source="p09-proof",
        source_version="P09-1",
        tags=["MEMORIA PLUS", "P09", "CORRELATION"],
        sharing_scope="SYSTEM_SHARED",
        idempotency_key=f"p09-{key}",
    )


def strong_assessment() -> dict:
    return {
        "hypothesis": {"statement": "intervention X causes outcome Y"},
        "intervention": {"description": "apply X under controlled protocol"},
        "comparator": {"kind": "CONTROL", "description": "matched untreated control"},
        "confounders": [{"name": "seasonality"}, {"name": "selection bias"}],
        "confounder_control": {"addressed": True, "method": "randomization+stratification"},
        "mechanism": {"supported": True, "description": "measured intermediate pathway"},
        "counterfactual": {"supported": True, "description": "control estimates outcome without X"},
        "attribution_confidence": 0.91,
        "sample_size": 120,
        "repetition_count": 3,
        "evidence": {
            "independent_refs": ["trial-A", "trial-B"],
            "replications_consistent": True,
            "proof": "MEMORIA_PLUS_P09",
        },
    }


def weak_assessment() -> dict:
    return {
        "hypothesis": {"statement": "success might mean X caused Y"},
        "intervention": {"description": "X happened"},
        "comparator": {},
        "confounders": [],
        "confounder_control": {"addressed": False},
        "mechanism": {"supported": False},
        "counterfactual": {"supported": False},
        "attribution_confidence": 0.99,
        "sample_size": 1,
        "repetition_count": 1,
        "evidence": {"success": True, "independent_refs": [], "replications_consistent": False},
    }


def create_assessment(item_id: str, payload: dict) -> tuple[int, dict]:
    return client.request("POST", f"/v1/memories/{item_id}/causal-assessments", payload=payload)


def promote(item_id: str, assessment_id: str, reason: str) -> tuple[int, dict]:
    return client.request(
        "POST",
        f"/v1/memories/{item_id}/causal-promotion",
        payload={"assessment_id": assessment_id, "reason": reason},
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


def db_policy(payload: dict) -> bool:
    conn = psycopg.connect(DSN, autocommit=True)
    try:
        conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',false)")
        row = conn.execute(
            """SELECT memory_causal_policy_eligible(
            'CORRELATION',%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s,%s::jsonb)""",
            (
                json.dumps(payload["hypothesis"]), json.dumps(payload["intervention"]), json.dumps(payload["comparator"]),
                json.dumps(payload["confounders"]), json.dumps(payload["confounder_control"]), json.dumps(payload["mechanism"]),
                json.dumps(payload["counterfactual"]), float(payload["attribution_confidence"]), int(payload["sample_size"]),
                int(payload["repetition_count"]), json.dumps(payload["evidence"]),
            ),
        ).fetchone()
        return bool(row[0])
    finally:
        conn.close()


suffix = uuid.uuid4().hex[:12]
marker = "P09_" + suffix.upper()
health = client.health()
unsigned_policy = raw_status("/v1/causal-policy")
status, policy = client.request("GET", "/v1/causal-policy")
require(status == 200, (status, policy))

# Direct CAUSE creation is blocked at the application boundary.
direct_cause_payload = {
    "namespace": "P09_PROOF",
    "memory_key": "direct-cause-" + suffix,
    "category": "CAUSE",
    "content": {"marker": marker},
    "content_text": "Direct cause creation must fail",
    "provenance": {"proof": "MEMORIA_PLUS_P09"},
    "confidence": 1.0,
    "source": "p09-proof",
    "source_version": "P09-1",
    "tags": ["P09", "CAUSE"],
}
status_direct_cause, direct_cause_body = client.request("POST", "/v1/memories", payload=direct_cause_payload)

# A successful outcome alone does not authorize causal promotion.
success_item = remember_correlation("success-alone-" + suffix, marker)
status, application = client.request(
    "POST",
    f"/v1/experience/applications?item_id={success_item}",
    payload={"action_ref": "p09-success-alone", "mission_id": "P09-SUCCESS-" + suffix, "context": {"proof": marker}},
)
require(status == 201, (status, application))
status, outcome = client.request(
    "POST",
    f"/v1/experience/applications/{application['application_id']}/outcome",
    payload={
        "success": True,
        "outcome_type": "P09_SUCCESS_ALONE",
        "expected": {"value": 1},
        "actual": {"value": 1, "sample_size": 1},
        "evidence": {"proof": marker},
    },
)
require(status == 201, (status, outcome))
status_success_transition, success_transition = client.request(
    "POST",
    f"/v1/memories/{success_item}/ontology-transition",
    payload={"to_category": "CAUSE", "reason": "success alone must not prove cause", "evidence": {"outcome_id": outcome["outcome_id"]}},
)

# Weak causal assessment is persisted as evidence but is not promotion-eligible.
main_item = remember_correlation("main-" + suffix, marker)
weak = weak_assessment()
status_weak, weak_result = create_assessment(main_item, weak)
require(status_weak == 201, (status_weak, weak_result))
status_weak_promotion, weak_promotion = promote(main_item, weak_result["assessment_id"], "weak evidence must fail")

# Strong assessment is eligible.
strong = strong_assessment()
status_strong, strong_result = create_assessment(main_item, strong)
require(status_strong == 201, (status_strong, strong_result))
status_list, assessment_list = client.request("GET", f"/v1/memories/{main_item}/causal-assessments")
require(status_list == 200, (status_list, assessment_list))

# Generic ontology transition remains closed even if an assessment id is supplied.
status_generic_cause, generic_cause = client.request(
    "POST",
    f"/v1/memories/{main_item}/ontology-transition",
    payload={
        "to_category": "CAUSE",
        "reason": "generic route must stay closed",
        "evidence": {"causal_assessment_id": strong_result["assessment_id"]},
    },
)

# A current eligible assessment becomes stale after a content revision.
stale_item = remember_correlation("stale-" + suffix, marker)
status, stale_assessment = create_assessment(stale_item, strong)
require(status == 201 and stale_assessment['eligible'], (status, stale_assessment))
stale_v1 = current_version(stale_item)
status_revision, revision = client.request(
    "POST",
    f"/v1/memories/{stale_item}/versions",
    payload={
        "content": {"marker": marker, "revision": 2},
        "content_text": "P09 stale causal assessment revision",
        "provenance": {"proof": "MEMORIA_PLUS_P09", "case": "stale"},
        "confidence": 0.76,
        "source": "p09-proof",
        "source_version": "P09-2",
        "tags": ["P09", "STALE_CAUSAL_ASSESSMENT"],
        "expected_version": int(stale_v1["version_no"]),
    },
)
require(status_revision == 201, (status_revision, revision))
status_stale_promotion, stale_promotion = promote(stale_item, stale_assessment["assessment_id"], "stale assessment must fail")

# Database boundary rejects direct CAUSE transition without an eligible assessment.
db_direct_update_state = sqlstate_for(
    "UPDATE memory_items SET category='CAUSE' WHERE item_id=%s AND set_config('app.ontology_transition_authorized','1',true)='1'",
    (success_item,),
)
db_generic_transition_state = sqlstate_for(
    "SELECT memory_apply_ontology_transition(%s,%s,'CAUSE','p09-sql','direct SQL without assessment','{}'::jsonb)",
    ("trn-p09-" + uuid.uuid4().hex, success_item),
)

# Python and PostgreSQL policy decisions must be identical.
strong_domain = evaluate_causal_assessment(source_category="CORRELATION", **strong)
weak_domain = evaluate_causal_assessment(source_category="CORRELATION", **weak)
strong_db = db_policy(strong)
weak_db = db_policy(weak)

# Dedicated promotion is the only application path that succeeds.
status_promotion, promotion = promote(main_item, strong_result["assessment_id"], "P09 strong causal evidence accepted")
require(status_promotion == 200, (status_promotion, promotion))
status_repeat_promotion, repeat_promotion = promote(main_item, strong_result["assessment_id"], "repeat must fail")

# Append-only protection after real rows exist.
assessment_update_state = sqlstate_for(
    "UPDATE memory_causal_assessments SET created_by='tamper' WHERE assessment_id=%s",
    (strong_result["assessment_id"],),
)
promotion_update_state = sqlstate_for(
    "UPDATE memory_causal_promotions SET actor_id='tamper' WHERE promotion_id=%s",
    (promotion["promotion_id"],),
)

with psycopg.connect(DSN, autocommit=True) as conn:
    conn.execute("SELECT set_config('app.current_tenant','__SYSTEM__',false)")
    schema = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
    causal_schema_version = conn.execute("SELECT value FROM schema_meta WHERE key='causal_policy_version'").fetchone()[0]
    main_db = conn.execute(
        "SELECT category,validation_status,governor_eligible,content_sha256 FROM memory_items WHERE item_id=%s",
        (main_item,),
    ).fetchone()
    promotion_db = conn.execute(
        """SELECT promotion_id,assessment_id,transition_id,item_id,version_id,content_sha256,
        from_category,to_category,policy_version FROM memory_causal_promotions WHERE promotion_id=%s""",
        (promotion["promotion_id"],),
    ).fetchone()
    transition_db = conn.execute(
        "SELECT evidence,from_category,to_category,version_id FROM memory_ontology_transitions WHERE transition_id=%s",
        (promotion["transition_id"],),
    ).fetchone()
    rls = conn.execute(
        "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname IN ('memory_causal_assessments','memory_causal_promotions') ORDER BY relname"
    ).fetchall()
    generated = conn.execute(
        "SELECT is_generated FROM information_schema.columns WHERE table_name='memory_causal_assessments' AND column_name='eligible'"
    ).fetchone()[0]
    migration = conn.execute(
        "SELECT checksum_sha256 FROM schema_migrations WHERE version='0023_causal_memory_policy'"
    ).fetchone()[0]
    audit_counts = dict(conn.execute(
        "SELECT event_type,count(*) FROM audit_events WHERE event_type IN ('CAUSAL_ASSESSMENT_RECORDED','CAUSAL_CAUSE_PROMOTED') GROUP BY event_type"
    ).fetchall())
    cause_count = conn.execute("SELECT count(*) FROM memory_items WHERE category='CAUSE'").fetchone()[0]

# RLS tenant isolation proof using a non-owning tenant context.
with psycopg.connect(DSN, autocommit=True) as conn:
    conn.execute("SELECT set_config('app.current_tenant',%s,false)", ("P09_OTHER_" + suffix.upper(),))
    isolated_count = conn.execute(
        "SELECT count(*) FROM memory_causal_assessments WHERE assessment_id=%s",
        (strong_result["assessment_id"],),
    ).fetchone()[0]

checks = {
    "api_0_17_0": health.get("version") == "0.17.0",
    "policy_requires_auth": unsigned_policy == 401,
    "policy_version": policy.get("version") == CAUSAL_POLICY_VERSION == "CP-1.0.0",
    "policy_explicit_thresholds": policy.get("thresholds") == causal_policy_spec()["thresholds"],
    "direct_cause_creation_api_422": status_direct_cause == 422,
    "successful_outcome_recorded": outcome.get("success") is True,
    "success_alone_cannot_promote_cause": status_success_transition == 422,
    "weak_assessment_recorded": status_weak == 201,
    "weak_assessment_ineligible": weak_result.get("eligible") is False and bool(weak_result.get("failure_reasons")),
    "weak_assessment_promotion_rejected": status_weak_promotion == 422,
    "strong_assessment_eligible": strong_result.get("eligible") is True and strong_result.get("failure_reasons") == [],
    "all_required_causal_criteria_pass": all(strong_result.get("criteria", {}).values()),
    "assessment_listing_contains_both": {weak_result["assessment_id"], strong_result["assessment_id"]}.issubset({x["assessment_id"] for x in assessment_list.get("assessments", [])}),
    "generic_cause_transition_closed": status_generic_cause == 422,
    "stale_assessment_promotion_409": status_stale_promotion == 409,
    "schema_direct_cause_update_rejected": db_direct_update_state == "23514",
    "schema_generic_cause_transition_rejected": db_generic_transition_state == "23514",
    "domain_db_strong_identical": strong_domain.eligible is True and strong_db is True,
    "domain_db_weak_identical": weak_domain.eligible is False and weak_db is False,
    "dedicated_causal_promotion_200": status_promotion == 200,
    "cause_promotion_exact": main_db[0] == "CAUSE" and promotion.get("from_category") == "CORRELATION" and promotion.get("to_category") == "CAUSE",
    "promotion_invalidates_validation": main_db[1] == "UNVALIDATED" and main_db[2] is False,
    "promotion_version_hash_bound": str(promotion_db[4]) == strong_result["version_id"] and str(promotion_db[5]) == strong_result["content_sha256"],
    "promotion_ledger_exact": str(promotion_db[0]) == promotion["promotion_id"] and str(promotion_db[1]) == strong_result["assessment_id"] and str(promotion_db[2]) == promotion["transition_id"],
    "ontology_transition_carries_assessment": transition_db[0].get("causal_assessment_id") == strong_result["assessment_id"] and transition_db[1] == "CORRELATION" and transition_db[2] == "CAUSE",
    "repeat_promotion_rejected": status_repeat_promotion == 422,
    "assessments_append_only": assessment_update_state == "55000",
    "promotions_append_only": promotion_update_state == "55000",
    "eligible_is_database_generated": generated == "ALWAYS",
    "causal_tables_force_rls": len(rls) == 2 and all(bool(x[1]) and bool(x[2]) for x in rls),
    "tenant_isolation_proven": isolated_count == 0,
    "causal_audit_events_recorded": int(audit_counts.get("CAUSAL_ASSESSMENT_RECORDED", 0)) >= 3 and int(audit_counts.get("CAUSAL_CAUSE_PROMOTED", 0)) >= 1,
    "schema_version": schema == "memory-0.17.0",
    "causal_schema_version": causal_schema_version == "CP-1.0.0",
    "migration_0023_checksum": migration == "696ee480795ced3fa49c2e9751c7315dd3420a65bdcf5d894df25a887f741d34",
    "cause_exists_only_after_policy_promotion": int(cause_count) >= 1,
}
failed = [name for name, passed in checks.items() if not passed]
result = {
    "generated_at": datetime.now(UTC).isoformat(),
    "tag": "MEMORIA PLUS",
    "priority": 9,
    "title": "Memória causal",
    "result": "PASS" if not failed else "FAIL",
    "failed": failed,
    "checks": checks,
    "api": {
        "version": health.get("version"),
        "unsigned_policy": unsigned_policy,
        "direct_cause_status": status_direct_cause,
        "success_transition_status": status_success_transition,
        "weak_promotion_status": status_weak_promotion,
        "generic_cause_status": status_generic_cause,
        "stale_promotion_status": status_stale_promotion,
        "dedicated_promotion_status": status_promotion,
    },
    "policy": policy,
    "schema": schema,
    "causal_policy_version": causal_schema_version,
    "main_item": main_item,
    "weak_assessment": weak_result,
    "strong_assessment": strong_result,
    "promotion": promotion,
    "sqlstates": {
        "direct_cause_update": db_direct_update_state,
        "generic_cause_transition": db_generic_transition_state,
        "assessment_update": assessment_update_state,
        "promotion_update": promotion_update_state,
    },
    "audit_counts": audit_counts,
    "cause_count": int(cause_count),
}

out_json = ROOT / "evidence/MEMORIA_PLUS_P09_PROOF.json"
out_md = ROOT / "evidence/MEMORIA_PLUS_P09_PROOF.md"
out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
md = [
    "# MEMORIA PLUS P09 — Prova de memória causal",
    "",
    f"- Resultado: **{result['result']}**",
    f"- API: `{health.get('version')}`",
    f"- Schema: `{schema}`",
    f"- Política causal: `{causal_schema_version}`",
    f"- Assessment forte elegível: `{strong_result.get('eligible')}`",
    "- Promoção: `CORRELATION -> CAUSE`",
    f"- Checks: `{sum(1 for x in checks.values() if x)}/{len(checks)}`",
    "",
    "## Garantias provadas",
    "",
    "- sucesso/expected/actual isolados não promovem CAUSE;",
    "- criação direta de CAUSE é rejeitada;",
    "- transição ontológica genérica para CAUSE é rejeitada;",
    "- assessment causal exige hipótese, intervenção, comparator/control, confounders, mecanismo, counterfactual, attribution confidence, sample size, repetição e evidência independente;",
    "- decisão de elegibilidade é idêntica no domínio Python e no PostgreSQL;",
    "- assessment é preso à versão/hash atual e se torna inutilizável após revisão;",
    "- promoção invalida validação/governor eligibility;",
    "- assessments e promotions são append-only e protegidos por FORCE RLS.",
]
out_md.write_text("\n".join(md), encoding="utf-8")
print(json.dumps({"result":result["result"],"failed":failed,"checks":checks,"schema":schema,"causal_policy_version":causal_schema_version}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not failed else 1)
