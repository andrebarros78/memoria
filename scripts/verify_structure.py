from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "memory_permanent"
REQUIRED = [
    ROOT / "pyproject.toml",
    SRC / "__init__.py",
    SRC / "domain.py",
    SRC / "input_guard.py",
    SRC / "store.py",
    SRC / "report.py",
    SRC / "api.py",
    SRC / "static" / "index.html",
    SRC / "static" / "styles.css",
    SRC / "static" / "app.js",
]
FORBIDDEN_IMPORT_MARKERS = ("from governor_windows", "import governor_windows", "from windows_mcp", "import windows_mcp")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED if not p.exists()]
    forbidden: list[dict[str, str]] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN_IMPORT_MARKERS:
            if marker in text:
                forbidden.append({"file": str(path.relative_to(ROOT)), "marker": marker})
    manifest = {str(p.relative_to(ROOT)): sha256(p) for p in REQUIRED if p.exists()}
    result = {
        "project_root": str(ROOT),
        "independent_root": ROOT.name == "MEMORIA-PERMANENTE",
        "missing": missing,
        "forbidden_imports": forbidden,
        "required_files": len(REQUIRED),
        "hashes": manifest,
        "P1_INDEPENDENT_MODULE": "PASS" if not missing and not forbidden and ROOT.name == "MEMORIA-PERMANENTE" else "FAIL",
    }
    evidence_dir = ROOT / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = evidence_dir / "P1_STRUCTURE_PROOF.json"
    evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["P1_INDEPENDENT_MODULE"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
