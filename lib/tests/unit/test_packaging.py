"""Every data file the library loads at runtime is declared as package data (#162).

An editable install reads files from the checkout, so a file missing from the
wheel goes unnoticed until someone installs the wheel: then creating a user
fails with FileNotFoundError on data/contact_schema.json.
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
_PACKAGE = "blue_data_user_source"
# Source-only: the input to tools/convert_schema.py, never read at runtime.
_NOT_SHIPPED = {"data/schema.txt"}


def _undeclared(root: Path, package: str, not_shipped: set[str]) -> list[str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    declared = pyproject["tool"]["setuptools"].get("package-data", {})
    top = root / "src" / package
    missing = []
    for path in sorted(top.rglob("*")):
        if path.is_dir() or path.suffix in (".py", ".pyc") or "__pycache__" in path.parts:
            continue
        if path.relative_to(top).as_posix() in not_shipped:
            continue
        owner = path.parent  # setuptools keys package data by the nearest package
        while not (owner / "__init__.py").exists():
            owner = owner.parent
        key = ".".join((package, *owner.relative_to(top).parts))
        name = path.relative_to(owner).as_posix()
        if not any(fnmatch.fnmatch(name, pattern) for pattern in declared.get(key, [])):
            missing.append(path.relative_to(top).as_posix())
    return missing


def test_every_data_file_is_declared_as_package_data() -> None:
    assert _undeclared(_ROOT, _PACKAGE, _NOT_SHIPPED) == []


def test_the_schemas_are_among_them() -> None:
    """Guards the guard: the files #162 lost are the ones it must look at."""
    data = _ROOT / "src" / _PACKAGE / "data"
    for name in ("schema.json", "metadata_schema.json", "contact_schema.json"):
        assert (data / name).is_file()
