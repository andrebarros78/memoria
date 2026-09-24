from pathlib import Path


def test_release_script_requires_runtime_resources_and_rejects_keys():
    root=Path(__file__).resolve().parents[1]
    text=(root/"scripts"/"build_release.ps1").read_text(encoding="utf-8-sig")
    for marker in (
        "memory_permanent/static/index.html",
        "share/memoria-permanente/.wmcp/product-dna.json",
        "share/memoria-permanente/migrations/",
        "expected_migrations=len(source_migrations)",
        "len(migrations)==expected_migrations",
        "'.dpapi'",
        "resource_ok",
    ):
        assert marker in text
