from __future__ import annotations

import hashlib
import json
from pathlib import Path

from memory_permanent.recovery_integrity_agent import RecoveryIntegrityAgent


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_accepts_artifact_inside_verification_root(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    artifact = root / "proof.json"
    artifact.write_text("proof", encoding="utf-8")
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps({"artifacts": [{"path": "proof.json", "sha256": _sha(artifact)}]}),
        encoding="utf-8",
    )

    check = RecoveryIntegrityAgent().verify_manifest(manifest, root=root)

    assert check.passed is True
    assert check.detail == "ok"


def test_manifest_rejects_parent_directory_escape(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps({"artifacts": [{"path": "../outside.txt", "sha256": _sha(outside)}]}),
        encoding="utf-8",
    )

    check = RecoveryIntegrityAgent().verify_manifest(manifest, root=root)

    assert check.passed is False
    assert "escapes verification root" in check.detail


def test_manifest_rejects_absolute_path_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps({"artifacts": [{"path": str(outside.resolve()), "sha256": _sha(outside)}]}),
        encoding="utf-8",
    )

    check = RecoveryIntegrityAgent().verify_manifest(manifest, root=root)

    assert check.passed is False
    assert "escapes verification root" in check.detail


def test_invalid_manifest_fails_closed(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{not-json", encoding="utf-8")

    check = RecoveryIntegrityAgent().verify_manifest(manifest)

    assert check.passed is False
    assert check.detail == "manifest is unreadable or invalid"
