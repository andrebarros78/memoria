from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_primary_launcher_executes_promoted_wheel_in_isolated_mode() -> None:
    launcher = (ROOT / "deploy" / "v5.3" / "start-primary-v53.ps1").read_text(encoding="utf-8")
    normalized = launcher.replace("/", "\\").lower()

    assert "remove-item env:pythonpath" in normalized
    assert "$env:pythonpath=\"$root\\src\"" not in normalized
    assert "runtime\\api-clean\\lib\\site-packages" in normalized
    assert "release integrity failure" in normalized
    assert "@('-i','-m','uvicorn'" in normalized
    assert "scripts\\runtime_preflight.py" not in normalized
    assert "-i -m memory_permanent.runtime_preflight" in normalized
    assert "from memory_permanent.runtime_preflight import verify_runtime_database" not in launcher


def test_runtime_preflight_is_executable_from_promoted_package() -> None:
    module = (ROOT / "src" / "memory_permanent" / "runtime_preflight.py").read_text(encoding="utf-8")
    assert "def main() -> int:" in module
    assert 'os.environ.get("MEMORY_DATABASE_URL", "")' in module
    assert 'if __name__ == "__main__":' in module
    assert "raise SystemExit(main())" in module


def test_recovery_accepts_only_canonical_isolated_api_process() -> None:
    recovery = (ROOT / ".agents" / "recovery" / "start-api.ps1").read_text(encoding="utf-8")
    normalized = recovery.replace("/", "\\").lower()

    assert "test-canonicalapiprocess" in normalized
    assert "runtime\\api-clean\\scripts\\python.exe" in normalized
    assert " -i " in normalized
    assert " -m uvicorn " in normalized
    assert "memory_permanent.api:app" in normalized
    assert "api_already_healthy_v53_isolated" in normalized
    assert "api_recovery_v53_isolated_ready" in normalized


def test_auditor_launch_and_provision_are_isolated_from_connector_pythonpath() -> None:
    run_script = (ROOT / ".agents" / "auditor" / "run.ps1").read_text(encoding="utf-8")
    provision = (ROOT / ".agents" / "auditor" / "provision.ps1").read_text(encoding="utf-8")
    lock = (ROOT / ".agents" / "auditor" / "requirements.lock.txt").read_text(encoding="utf-8")

    assert "$env:PYTHONPATH = ''" in run_script
    assert " -I " in run_script
    assert "$env:PYTHONPATH = ''" in provision
    assert "--only-binary=:all:" in provision
    assert "windows-mcp==" not in lock.lower()


def test_background_workers_do_not_inject_source_tree() -> None:
    for relative in ("scripts/conversation_ingestion_worker.py", "scripts/embedding_worker.py"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        normalized = text.replace("/", "\\").lower()
        assert "sys.path.insert" not in normalized
        assert 'root / "src"' not in normalized
        assert "from memory_permanent." in text

def test_canonical_api_and_workers_strip_inherited_pythonpath() -> None:
    for relative in (
        "deploy/canonical/start-canonical.ps1",
        "deploy/canonical/start-workers.ps1",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        normalized = text.replace("/", "\\").lower()
        assert "remove-item env:pythonpath" in normalized
        assert "pythonnousersite" in normalized
        assert " -i" in normalized or "'-i'" in normalized
