from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(r"C:\New Projet\MEMORIA_PERMANENTE_CANONICAL_1.0")
sys.path.insert(0, str(ROOT / "src"))

from memory_permanent.runtime_preflight import verify_runtime_database  # noqa: E402


def main() -> int:
    dsn = os.getenv("MEMORY_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("MEMORY_DATABASE_URL is required")
    result = verify_runtime_database(dsn)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
