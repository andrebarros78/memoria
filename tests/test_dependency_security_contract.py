import tomllib
from pathlib import Path

from packaging.requirements import Requirement


def test_cryptography_dependency_requires_patched_major_line():
    project=tomllib.loads((Path(__file__).resolve().parents[1]/"pyproject.toml").read_text(encoding="utf-8"))["project"]
    req=next(Requirement(x) for x in project["dependencies"] if Requirement(x).name=="cryptography")
    assert req.specifier.contains("50.0.0")
    assert not req.specifier.contains("46.0.7")
