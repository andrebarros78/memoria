from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.getenv("MEMORY_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
if importlib.util.find_spec("memory_permanent") is None:
    sys.path.insert(0, str(ROOT / "src"))

from memory_permanent.access_policy import AgentAccessContext  # noqa: E402
from memory_permanent.consolidation_policy import (  # noqa: E402
    ConsolidationMode,
    SchedulerSignals,
)
from memory_permanent.consolidation_scheduler import (  # noqa: E402
    ConsolidationScheduler,
)
from memory_permanent.store import PostgresMemoryStore  # noqa: E402


def _enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser(description="One-shot F04 cognitive consolidation worker")
    parser.add_argument("--mode", choices=[mode.value for mode in ConsolidationMode], default="IDLE_CONSOLIDATION")
    parser.add_argument("--scope-key", required=True)
    parser.add_argument("--recover-run", default="")
    parser.add_argument("--system-idle", action="store_true")
    parser.add_argument("--maintenance-window", action="store_true")
    parser.add_argument("--event-threshold-met", action="store_true")
    parser.add_argument("--memory-pressure", action="store_true")
    parser.add_argument("--cpu-percent", type=float, default=0.0)
    parser.add_argument("--unconsolidated-salience", type=float, default=1.0)
    args = parser.parse_args()

    if not _enabled("COGNITIVE_CONSOLIDATION"):
        print(json.dumps({"status": "DISABLED", "feature_flag": "COGNITIVE_CONSOLIDATION"}, sort_keys=True))
        return 0

    dsn = os.getenv("MEMORY_DATABASE_URL", "").strip() or os.getenv("MEMORY_DSN", "").strip()
    tenant = os.getenv("MEMORY_CONSOLIDATION_TENANT", "").strip()
    agent_id = os.getenv("MEMORY_CONSOLIDATION_AGENT", "cognitive-consolidation-worker").strip()
    if not dsn or not tenant or not agent_id:
        raise SystemExit("MEMORY_DATABASE_URL/MEMORY_DSN, MEMORY_CONSOLIDATION_TENANT and agent identity are required")

    access = AgentAccessContext.build(
        agent_id=agent_id,
        user_id=os.getenv("MEMORY_CONSOLIDATION_USER", "").strip() or None,
        project_id=os.getenv("MEMORY_CONSOLIDATION_PROJECT", "").strip() or None,
        team_id=os.getenv("MEMORY_CONSOLIDATION_TEAM", "").strip() or None,
        organization_id=os.getenv("MEMORY_CONSOLIDATION_ORG", "").strip() or None,
    )
    store = PostgresMemoryStore(dsn, initialize=False, tenant_id=tenant, access=access)
    scheduler = ConsolidationScheduler(store)

    if args.recover_run:
        result = scheduler.recover_run(args.recover_run)
    else:
        signals = SchedulerSignals(
            system_idle=bool(args.system_idle),
            queue_healthy=_enabled("MEMORY_OPERATIONAL_QUEUE_HEALTHY"),
            database_healthy=_enabled("MEMORY_DATABASE_HEALTHY"),
            recovery_in_progress=_enabled("MEMORY_RECOVERY_IN_PROGRESS"),
            io_budget_available=_enabled("MEMORY_IO_BUDGET_AVAILABLE"),
            cpu_percent=float(args.cpu_percent),
            unconsolidated_salience=float(args.unconsolidated_salience),
            maintenance_window=bool(args.maintenance_window),
            event_threshold_met=bool(args.event_threshold_met),
            memory_pressure=bool(args.memory_pressure),
        )
        result = scheduler.run_once(
            scope_key=args.scope_key,
            mode=ConsolidationMode(args.mode),
            signals=signals,
        )
    print(json.dumps(result.as_dict(), sort_keys=True))
    return 0 if result.status in {"COMPLETED", "SKIPPED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
