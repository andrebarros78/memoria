from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "CANONICAL_SECRET_SCAN.json"
MAX_BLOB = 5 * 1024 * 1024

PATTERNS = {
    "AWS_ACCESS_KEY": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "OPENAI_STYLE_KEY": re.compile(rb"sk-[A-Za-z0-9_-]{24,}"),
    "GITHUB_TOKEN": re.compile(rb"gh[pousr]_[A-Za-z0-9]{24,}"),
    "PRIVATE_KEY": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "BEARER_LITERAL": re.compile(rb"(?i)authorization\s*[:=]\s*['\"]?bearer\s+[A-Za-z0-9._~-]{24,}"),
    "PASSWORD_LITERAL": re.compile(rb"(?i)(?<!['\"])(?:password|passwd|pwd)\s*[:=]\s*['\"][^'\"\r\n]{12,}['\"]"),
}
FORBIDDEN_NAMES = {".env", "credentials.json", "secrets.json", "service-account.json", "pgpass.conf"}
FORBIDDEN_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".jks", ".keystore"}
TEXT_SUFFIXES = {".py", ".ps1", ".md", ".json", ".toml", ".yaml", ".yml", ".txt", ".sql", ".ini", ".cfg", ".js", ".css", ".html"}


def run(*args: str, input_data: bytes | None = None) -> bytes:
    return subprocess.check_output(args, cwd=ROOT, stderr=subprocess.DEVNULL, input=input_data)


def classify_finding(path: str, pattern_name: str, data: bytes, match: re.Match[bytes]) -> str:
    lower_path = path.replace("\\", "/").lower()
    line_start = data.rfind(b"\n", 0, match.start()) + 1
    line_end = data.find(b"\n", match.end())
    if line_end < 0:
        line_end = len(data)
    line = data[line_start:line_end].lower()
    if pattern_name == "PRIVATE_KEY" and lower_path.endswith("src/memory_permanent/secret_sanitizer.py"):
        return "DETECTOR_LITERAL"
    if pattern_name == "PRIVATE_KEY" and lower_path.endswith("tests/test_security_audit_v53.py") and b"opaque-private-material" in data.lower():
        return "TEST_FIXTURE_OPAQUE"
    if pattern_name == "PASSWORD_LITERAL" and b"admin_dsn" in line and b"password=" in line:
        return "DSN_SYNTAX_CHECK"
    return "UNADJUDICATED"


def scan_bytes(data: bytes, label: str, origin: str) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for pattern_name, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            line_no = data.count(b"\n", 0, match.start()) + 1
            findings.append({
                "origin": origin,
                "path": label,
                "line": line_no,
                "pattern": pattern_name,
                "classification": classify_finding(label, pattern_name, data, match),
            })
    return findings


def current_scan() -> tuple[list[dict[str, object]], list[str]]:
    findings: list[dict[str, object]] = []
    forbidden: list[str] = []
    paths = [p for p in run("git", "ls-files", "-z").decode("utf-8", "replace").split("\x00") if p]
    for rel in paths:
        p = ROOT / rel
        lower_name = p.name.lower()
        if lower_name in FORBIDDEN_NAMES or p.suffix.lower() in FORBIDDEN_SUFFIXES:
            forbidden.append(rel)
        if p.suffix.lower() not in TEXT_SUFFIXES or not p.is_file() or p.stat().st_size > MAX_BLOB:
            continue
        findings.extend(scan_bytes(p.read_bytes(), rel, "WORKTREE_TRACKED"))
    return findings, forbidden


def history_scan() -> list[dict[str, object]]:
    object_rows = run("git", "rev-list", "--objects", "--all").splitlines()
    if not object_rows:
        return []
    checked = run(
        "git", "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize) %(rest)",
        input_data=b"\n".join(object_rows) + b"\n",
    ).decode("utf-8", "replace").splitlines()
    candidates: list[tuple[str, str, int]] = []
    seen_sha: set[str] = set()
    for row in checked:
        parts = row.split(" ", 3)
        if len(parts) < 3:
            continue
        sha, obj_type, size_text = parts[:3]
        path = parts[3] if len(parts) == 4 else ""
        if obj_type != "blob" or sha in seen_sha:
            continue
        try:
            size = int(size_text)
        except ValueError:
            continue
        suffix = Path(path).suffix.lower()
        name = Path(path).name.lower()
        if size > MAX_BLOB or (suffix not in TEXT_SUFFIXES and name not in FORBIDDEN_NAMES):
            continue
        seen_sha.add(sha)
        candidates.append((sha, path or sha, size))

    findings: list[dict[str, object]] = []
    proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdin is not None and proc.stdout is not None
    try:
        for sha, path, expected_size in candidates:
            proc.stdin.write((sha + "\n").encode("ascii"))
            proc.stdin.flush()
            header = proc.stdout.readline().decode("ascii", "replace").strip().split()
            if len(header) < 3 or header[1] != "blob":
                continue
            size = int(header[2])
            data = proc.stdout.read(size)
            proc.stdout.read(1)
            if size != expected_size:
                continue
            for finding in scan_bytes(data, path, "GIT_HISTORY_BLOB"):
                finding["blob"] = sha
                findings.append(finding)
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)
    dedup = {(f.get("blob"), f.get("path"), f.get("line"), f.get("pattern")): f for f in findings}
    return list(dedup.values())


def main() -> int:
    current, forbidden = current_scan()
    history = history_scan()
    all_findings = current + history
    confirmed = [f for f in all_findings if f.get("classification") == "UNADJUDICATED"]
    adjudicated = [f for f in all_findings if f.get("classification") != "UNADJUDICATED"]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "MEMORIA_PERMANENTE_CANONICAL_1.0",
        "secret_values_emitted": False,
        "scanner_policy": "Only unadjudicated matches fail the gate; known detector literals, opaque fixtures, and DSN syntax checks remain recorded but do not count as leaked credentials.",
        "current_tracked_findings": current,
        "history_findings": history,
        "adjudicated_non_secret_findings": adjudicated,
        "confirmed_secret_findings": confirmed,
        "forbidden_tracked_secret_filenames": forbidden,
        "current_raw_findings_count": len(current),
        "history_raw_findings_count": len(history),
        "adjudicated_non_secret_count": len(adjudicated),
        "confirmed_secret_findings_count": len(confirmed),
        "forbidden_filename_count": len(forbidden),
        "status": "PASS" if not confirmed and not forbidden else "FAIL_REVIEW_REQUIRED",
    }
    EVIDENCE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "current_raw_findings_count", "history_raw_findings_count", "adjudicated_non_secret_count", "confirmed_secret_findings_count", "forbidden_filename_count", "secret_values_emitted")}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
