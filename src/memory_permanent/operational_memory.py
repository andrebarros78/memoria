from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

OPERATIONAL_MEMORY_VERSION = "OM-1.0.0"


class OperationalStatus(StrEnum):
    PROVEN = "PROVEN"
    STALE = "STALE"
    FAILED = "FAILED"
    DEPRECATED = "DEPRECATED"


class OperationalProofType(StrEnum):
    REPLAY = "REPLAY"
    RECOVERY = "RECOVERY"


class OperationalProofResult(StrEnum):
    PASS = "PASS"  # nosec B105 - proof-result enum value, not a credential
    FAIL = "FAIL"


_KEY_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,159}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def normalize_operational_key(value: str, field: str) -> str:
    key = str(value or "").strip().upper()
    if not _KEY_RE.fullmatch(key):
        raise ValueError(f"{field} must match {_KEY_RE.pattern}")
    return key


def normalize_version_label(value: str) -> str:
    label = str(value or "").strip()
    if not label or len(label) > 120:
        raise ValueError("skill version label is required and must be <= 120 chars")
    return label


def normalize_sha256(value: str, field: str = "sha256") -> str:
    digest = str(value or "").strip().lower()
    if not _SHA_RE.fullmatch(digest):
        raise ValueError(f"{field} must be 64 lowercase hexadecimal characters")
    return digest


def validate_competency_record(*, competency_key: str, title: str, description: str, domain: str) -> dict[str, str]:
    key = normalize_operational_key(competency_key, "competency_key")
    title_value = str(title or "").strip()
    description_value = str(description or "").strip()
    domain_value = normalize_operational_key(domain or "GENERAL", "domain")
    if not title_value or len(title_value) > 300:
        raise ValueError("competency title is required and must be <= 300 chars")
    if len(description_value) > 8000:
        raise ValueError("competency description must be <= 8000 chars")
    return {"competency_key": key, "title": title_value, "description": description_value, "domain": domain_value}


def validate_skill_record(*, skill_key: str, title: str, description: str) -> dict[str, str]:
    key = normalize_operational_key(skill_key, "skill_key")
    title_value = str(title or "").strip()
    description_value = str(description or "").strip()
    if not title_value or len(title_value) > 300:
        raise ValueError("skill title is required and must be <= 300 chars")
    if len(description_value) > 8000:
        raise ValueError("skill description must be <= 8000 chars")
    return {"skill_key": key, "title": title_value, "description": description_value}


def validate_skill_version_record(
    *, version_label: str, implementation_version: str, implementation_sha256: str, contract: dict[str, Any]
) -> dict[str, Any]:
    version = normalize_version_label(version_label)
    implementation = str(implementation_version or "").strip()
    if not implementation or len(implementation) > 120:
        raise ValueError("implementation_version is required and must be <= 120 chars")
    if not isinstance(contract, dict) or not contract:
        raise ValueError("skill version contract must be a non-empty object")
    return {
        "version_label": version,
        "implementation_version": implementation,
        "implementation_sha256": normalize_sha256(implementation_sha256, "implementation_sha256"),
        "contract": dict(contract),
    }


def validate_capability_record(*, capability_key: str, contract: dict[str, Any]) -> dict[str, Any]:
    key = normalize_operational_key(capability_key, "capability_key")
    if not isinstance(contract, dict) or not contract:
        raise ValueError("capability contract must be a non-empty object")
    return {"capability_key": key, "contract": dict(contract)}


def validate_proof_record(
    *, proof_type: str, result: str, artifact_ref: str, artifact_sha256: str, evidence: dict[str, Any]
) -> dict[str, Any]:
    kind = OperationalProofType(str(proof_type).strip().upper())
    outcome = OperationalProofResult(str(result).strip().upper())
    ref = str(artifact_ref or "").strip()
    if not ref or len(ref) > 500:
        raise ValueError("proof artifact_ref is required and must be <= 500 chars")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("operational proof evidence must be a non-empty object")
    return {
        "proof_type": kind.value,
        "result": outcome.value,
        "artifact_ref": ref,
        "artifact_sha256": normalize_sha256(artifact_sha256, "artifact_sha256"),
        "evidence": dict(evidence),
    }


def validate_status_record(*, status: str, reason: str, evidence: dict[str, Any]) -> dict[str, Any]:
    state = OperationalStatus(str(status).strip().upper())
    reason_value = str(reason or "").strip()
    if not reason_value or len(reason_value) > 4000:
        raise ValueError("operational status reason is required and must be <= 4000 chars")
    if not isinstance(evidence, dict):
        raise ValueError("operational status evidence must be an object")
    return {"status": state.value, "reason": reason_value, "evidence": dict(evidence)}


def operational_memory_spec() -> dict[str, Any]:
    return {
        "version": OPERATIONAL_MEMORY_VERSION,
        "entities": ["COMPETENCY", "SKILL", "SKILL_VERSION", "CAPABILITY"],
        "statuses": [x.value for x in OperationalStatus],
        "proof_types": [x.value for x in OperationalProofType],
        "proof_results": [x.value for x in OperationalProofResult],
        "proven_gate": {
            "required": ["REPLAY:PASS", "RECOVERY:PASS"],
            "binding": "SKILL_VERSION + IMPLEMENTATION_SHA256 + IMMUTABLE_EVIDENCE",
        },
        "status_rules": {
            "PROVEN": "requires passing replay and recovery proofs",
            "STALE": "previously proven capability is no longer current or its evidence is stale",
            "FAILED": "a proof execution failed",
            "DEPRECATED": "terminal status; version cannot return to active service",
        },
        "invariants": [
            "competencies, skills, skill versions, capabilities, proofs and status events are tenant-isolated",
            "proof and status history is append-only",
            "a skill version cannot become PROVEN without replay and recovery PASS evidence",
            "a new superseding skill version marks the prior PROVEN version STALE",
            "FAILED proof automatically records FAILED status",
            "when both required proofs PASS, the skill version automatically records PROVEN status",
            "DEPRECATED is terminal",
            "catalog exposes exact version, implementation hash, evidence and current status",
        ],
    }
