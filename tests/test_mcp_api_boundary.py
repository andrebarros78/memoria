from pathlib import Path


def test_mcp_server_uses_signed_api_boundary_only():
    source=(Path(__file__).resolve().parents[1]/"src"/"memory_permanent"/"mcp_server.py").read_text(encoding="utf-8")
    assert "SignedMemoryClient" in source
    assert "PostgresMemoryStore" not in source
    assert "MEMORY_DATABASE_URL" not in source
    assert 'version="0.3.0"' in source
