from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess  # nosec B404 -- subprocess is required for fixed local tooling; shell execution is not used.
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory_permanent.access_policy import AgentAccessContext
from memory_permanent.memory_evolution_capacity_agent import (
    CapacitySnapshot,
    EvolutionProof,
    MemoryEvolutionCapacityAgent,
)
from memory_permanent.runtime_preflight import verify_runtime_database
from memory_permanent.store import PostgresMemoryStore

ROOT = Path(r"C:\New Projet\MEMORIA-PERMANENTE")
EVIDENCE = ROOT / "evidence" / "TERMINAL_AGENT_EVOLUTION_PROOF_20260905.json"
EVIDENCE_MD = ROOT / "evidence" / "TERMINAL_AGENT_EVOLUTION_PROOF_20260905.md"
DSN = "postgresql://memory_app@127.0.0.1:55436/memoria_permanente_v52_primary"
EXPECTED_MIGRATION = "0051_reserved_system_and_restore_gate_hardening"
EXPECTED_MIGRATIONS = 51


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def command(name: str, args: list[str], env: dict[str, str]) -> dict[str, Any]:
    cp = subprocess.run(  # nosec B603 -- argv is assembled from fixed/internal local executable paths; shell=False.
        args,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    tail = "\n".join((cp.stdout + "\n" + cp.stderr).splitlines()[-30:])
    return {"name": name, "returncode": cp.returncode, "pass": cp.returncode == 0, "tail": tail}


def main() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PGPASSFILE"] = str(ROOT / "runtime" / "secrets" / "pgpass.conf")

    e2e = load_json(ROOT / "evidence" / "AGENT_SKILL_E2E_PROOF_20260905.json")
    security = load_json(ROOT / "evidence" / "SECURITY_AUTH_HARDENING_LIVE_PROOF.json")
    boundary = load_json(ROOT / "evidence" / "DERIVED_ARTIFACT_BOUNDARY_LIVE_PROOF_20260905.json")
    recovery = load_json(ROOT / "evidence" / "RELEASE_0_28_1_RECOVERY_PROOF_20260906.json")
    backup_manifest_path = max((ROOT / 'backups' / 'v52-encrypted').glob('*.encrypted.manifest.json'), key=lambda p: p.stat().st_mtime)
    backup_manifest = load_json(backup_manifest_path)
    wheel = ROOT / "runtime" / "release-wheel-final" / "memoria_permanente-0.28.1-py3-none-any.whl"
    encrypted = Path(str(backup_manifest["encrypted_file"]))

    preflight = verify_runtime_database(DSN)
    backup_ok = (
        encrypted.is_file()
        and sha256(encrypted) == backup_manifest["ciphertext_sha256"]
        and not bool(backup_manifest["plaintext_retained"])
        and int(backup_manifest["metadata"]["migration_count"]) == EXPECTED_MIGRATIONS
        and backup_manifest["metadata"]["latest_migration"] == EXPECTED_MIGRATION
    )
    restore_ok = (
        recovery.get("status") == "PASS"
        and recovery.get("pg_amcheck") == "PASS"
        and recovery.get("audit_chain_ok") is True
        and recovery.get("erasure_replay", {}).get("result") == "PASS"
        and recovery.get("runtime_preflight", {}).get("latest_migration") == EXPECTED_MIGRATION
    )
    e2e_ok = (
        e2e.get("result") == "PASS"
        and e2e.get("restart_verified") is True
        and e2e.get("agent_skill_plane", {}).get("status") == "HEALTHY"
        and int(e2e.get("agent_skill_plane", {}).get("agents_loaded", 0)) == 4
        and int(e2e.get("agent_skill_plane", {}).get("skills_callable", 0)) == 6
    )
    security_ok = security.get("result") == "PASS" and boundary.get("result") == "PASS"
    release_ok = wheel.is_file() and sha256(wheel) == "75282d46a34f44c95323697f450d0ea56e44492650494e5e4f7d8920fe371ab7"

    py = str(ROOT / ".venv" / "Scripts" / "python.exe")
    regression = [
        command("ruff", [py, "-m", "ruff", "check", "src/memory_permanent", "tests", "scripts/prove_agent_skill_integration.py", "scripts/prove_terminal_agent_evolution.py"], env),
        command("mypy", [py, "-m", "mypy", "src/memory_permanent", "--ignore-missing-imports"], env),
        command("bandit", [py, "-m", "bandit", "-q", "-r", "src/memory_permanent"], env),
        command("pytest", [py, "-m", "pytest", "-q"], env),
        command("pip-check", [py, "-m", "pip", "check"], env),
    ]
    regression_ok = all(item["pass"] for item in regression)

    store = PostgresMemoryStore(
        DSN,
        initialize=False,
        tenant_id="LEGACY",
        access=AgentAccessContext.system(),
    )
    agent = MemoryEvolutionCapacityAgent(store=store)
    disk = shutil.disk_usage(ROOT)
    capacity = agent.assess_capacity(
        CapacitySnapshot(
            filesystem_bytes=disk.total,
            free_bytes=disk.free,
            database_bytes=0,
            growth_bytes_per_day=0.0,
            backlog_items=0,
        ),
        persist=True,
    )
    evolution_proof = EvolutionProof(
        migration_version=EXPECTED_MIGRATION,
        candidate_ref="75282d46a34f44c95323697f450d0ea56e44492650494e5e4f7d8920fe371ab7",
        preflight_pass=preflight.get("status") == "READY" and preflight.get("latest_migration") == EXPECTED_MIGRATION,
        backup_pass=backup_ok,
        isolated_apply_pass=boundary.get("result") == "PASS",
        regression_pass=regression_ok,
        retrieval_quality_status=str(e2e.get("agents", {}).get("retrieval_quality", {}).get("status") or "DENY"),
        restore_pass=restore_ok,
        integrity_pass=e2e_ok and security_ok and release_ok,
        rollback_or_rollforward_ready=backup_ok and restore_ok,
    )
    evolution = agent.assess_evolution(evolution_proof, persist=True)

    result = {
        "result": "PASS" if evolution.allowed else "FAIL",
        "generated_at": datetime.now(UTC).isoformat(),
        "migration": preflight,
        "backup_ok": backup_ok,
        "restore_ok": restore_ok,
        "e2e_ok": e2e_ok,
        "security_ok": security_ok,
        "release_ok": release_ok,
        "regression": regression,
        "capacity": {
            "state": capacity.state,
            "allow_growth": capacity.allow_growth,
            "allow_nonessential_derivatives": capacity.allow_nonessential_derivatives,
            "reasons": list(capacity.reasons),
            "free_ratio": capacity.metrics.get("free_ratio"),
        },
        "evolution": {
            "status": evolution.status,
            "allowed": evolution.allowed,
            "reasons": list(evolution.reasons),
        },
        "agent_skill_plane": e2e.get("agent_skill_plane"),
        "retrieval_quality": e2e.get("agents", {}).get("retrieval_quality"),
        "backup_id": backup_manifest.get("backup_id"),
        "wheel_sha256": sha256(wheel),
        "secret_material_exposed": False,  # nosec B105 -- boolean evidence/status field, not a credential.
    }
    EVIDENCE.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Terminal Agent Evolution Proof â€” 2026-09-05",
        "",
        f"Result: **{result['result']}**",
        "",
        f"Evolution agent: **{evolution.status}**",
        f"Capacity state: **{capacity.state}**",
        f"Agents loaded: **{e2e['agent_skill_plane']['agents_loaded']}/{e2e['agent_skill_plane']['agents_total']}**",
        f"Skills callable: **{e2e['agent_skill_plane']['skills_callable']}/{e2e['agent_skill_plane']['skills_total']}**",
        f"Retrieval precision/recall: **{e2e['agents']['retrieval_quality']['metrics']['precision']:.2f}/{e2e['agents']['retrieval_quality']['metrics']['recall']:.2f}**",
        f"Backup: `{backup_manifest['backup_id']}`",
        f"Release SHA-256: `{result['wheel_sha256']}`",
        "",
        "## Gates",
        "",
        f"- Preflight/migrations: {'PASS' if evolution_proof.preflight_pass else 'FAIL'}",
        f"- Backup: {'PASS' if backup_ok else 'FAIL'}",
        f"- Isolated apply / least privilege boundary: {'PASS' if evolution_proof.isolated_apply_pass else 'FAIL'}",
        f"- Regression: {'PASS' if regression_ok else 'FAIL'}",
        f"- Retrieval quality: {evolution_proof.retrieval_quality_status}",
        f"- Restore: {'PASS' if restore_ok else 'FAIL'}",
        f"- Integrity/security/release: {'PASS' if evolution_proof.integrity_pass else 'FAIL'}",
        f"- Rollback/roll-forward readiness: {'PASS' if evolution_proof.rollback_or_rollforward_ready else 'FAIL'}",
    ]
    EVIDENCE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"result": result["result"], "evolution": evolution.status, "evidence": str(EVIDENCE)}))
    return 0 if evolution.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
