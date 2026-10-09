"""An invalid user name is rejected before anything is written (#146)."""
from __future__ import annotations

from pathlib import Path

import pytest

from blue_data_user_source import FileUserSource, QueryError, validate_user_name


def _file_props(base: Path, name: str) -> dict:
    user_dir = base / "sources" / name
    return dict(
        registry_props={"backend": "file", "path": str(base / "registries" / f"{name}.json")},
        kb_source_props={"backend": "memory"},
        metadata_source_props={"backend": "file", "path": str(user_dir / "metadata.json")},
        contact_source_props={"backend": "file", "path": str(user_dir / "contacts.json")},
        session_source_props={"backend": "file", "path": str(user_dir / "sessions.json")},
    )


@pytest.mark.parametrize("name", ["..", ".", "a.b", "a/b", "/abs", "-x", "", "x" * 65, "a b", None, 7])
def test_invalid_names_are_rejected(name) -> None:
    with pytest.raises(QueryError, match="invalid database name"):
        validate_user_name(name)


@pytest.mark.parametrize("name", ["alice", "Alice_2", "_private", "a-b", "x" * 64, "0"])
def test_valid_names_pass(name) -> None:
    assert validate_user_name(name) == name


async def test_create_user_with_an_invalid_name_writes_nothing(tmp_path: Path) -> None:
    us = FileUserSource("user_source", {"connection": {"path": str(tmp_path / "registry.json")}})
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))

    with pytest.raises(QueryError, match="invalid database name '..'"):
        await us.create_user("..", **_file_props(tmp_path, ".."), onboard=False)

    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before
    assert us.list_users() == []


async def test_create_user_accepts_a_leading_underscore(tmp_path: Path) -> None:
    us = FileUserSource("user_source", {"connection": {"path": str(tmp_path / "registry.json")}})
    await us.create_user("_private", **_file_props(tmp_path, "_private"), onboard=False)
    assert us.list_users() == ["_private"]
