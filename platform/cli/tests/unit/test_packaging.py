"""profile_spec.json is declared as package data (#162).

An editable install reads it from the checkout, so its absence from the wheel
went unnoticed: installed from a wheel, every command failed with
FileNotFoundError, `profile list` included.
"""
from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = "blue_data_user_cli"


def test_every_data_file_is_declared_as_package_data() -> None:
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = pyproject["tool"]["setuptools"].get("package-data", {}).get(_PACKAGE, [])
    top = _ROOT / "src" / _PACKAGE
    data_files = [
        p.name for p in top.iterdir()
        if p.is_file() and p.suffix not in (".py", ".pyc")
    ]
    assert "profile_spec.json" in data_files
    assert [n for n in data_files if not any(fnmatch.fnmatch(n, g) for g in declared)] == []
