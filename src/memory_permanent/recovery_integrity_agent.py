from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class IntegrityCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class RecoveryIntegrityReport:
    passed: bool
    checks: tuple[IntegrityCheck, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [
                c.__dict__
                if hasattr(c, "__dict__")
                else {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in self.checks
            ],
        }


class RecoveryIntegrityAgent:
    """Independent verifier for evidence, backup artifacts and recovery proofs.

    It performs read-only verification and never mutates the canonical database.
    Manifest entries are constrained to the declared verification root so an
    untrusted or corrupted manifest cannot make the verifier inspect arbitrary
    files outside the recovery artifact boundary.
    """

    @staticmethod
    def sha256(path: str | Path) -> str:
        h = hashlib.sha256()
        with Path(path).open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def verify_file_hash(self, path: str | Path, expected_sha256: str) -> IntegrityCheck:
        p = Path(path)
        if not p.is_file():
            return IntegrityCheck("file_hash", False, f"missing:{p}")
        actual = self.sha256(p)
        ok = actual == str(expected_sha256).strip().lower()
        return IntegrityCheck("file_hash", ok, f"{p.name}:{actual}")

    @staticmethod
    def _contained_target(base: Path, candidate: str | Path) -> Path | None:
        root = base.resolve()
        raw = Path(candidate)
        target = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
        if target != root and root not in target.parents:
            return None
        return target

    def verify_manifest(self, manifest_path: str | Path, *, root: str | Path | None = None) -> IntegrityCheck:
        p = Path(manifest_path)
        if not p.is_file():
            return IntegrityCheck("manifest", False, f"missing:{p}")
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            return IntegrityCheck("manifest", False, "manifest is unreadable or invalid")
        entries = data.get("artifacts") or data.get("files") or []
        if not isinstance(entries, list) or not entries:
            return IntegrityCheck("manifest", False, "manifest has no artifacts")
        base = Path(root) if root else p.parent
        failures: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                failures.append("manifest entry is invalid")
                continue
            rel = entry.get("path") or entry.get("artifact")
            expected = entry.get("sha256")
            if not rel or not expected:
                failures.append("entry missing path/sha256")
                continue
            target = self._contained_target(base, str(rel))
            if target is None:
                failures.append("entry path escapes verification root")
                continue
            check = self.verify_file_hash(target, str(expected))
            if not check.passed:
                failures.append(check.detail)
        return IntegrityCheck("manifest", not failures, "ok" if not failures else ";".join(failures))

    @staticmethod
    def verify_exit_evidence(name: str, exit_code: int, detail: str = "") -> IntegrityCheck:
        return IntegrityCheck(name, int(exit_code) == 0, detail or f"exit_code={int(exit_code)}")

    def assess(
        self,
        *,
        pg_amcheck_exit: int,
        restore_exit: int,
        regression_exit: int,
        security_scan_exit: int,
        manifest_check: IntegrityCheck,
    ) -> RecoveryIntegrityReport:
        checks = (
            self.verify_exit_evidence("pg_amcheck", pg_amcheck_exit),
            self.verify_exit_evidence("restore", restore_exit),
            self.verify_exit_evidence("regression", regression_exit),
            self.verify_exit_evidence("security_scan", security_scan_exit),
            manifest_check,
        )
        return RecoveryIntegrityReport(passed=all(c.passed for c in checks), checks=checks)
