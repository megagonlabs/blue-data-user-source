"""create_database works with no properties, through the DataSource interface (#165).

It used to need all five store configs and failed on a bare ``KeyError:
'registry'`` without them; each front end kept its own copy of the layout.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from blue_data_user_source import (
    FileUserSource,
    MemoryUserSource,
    QueryError,
    RedisUserSource,
    UserExistsError,
)
from blue_data_user_source.data.manager import CLS_KB_MEMORY


def _file_source(root: Path) -> FileUserSource:
    return FileUserSource("u", {"connection": {"path": str(root / "registry.json")}})


def test_memory_source_needs_no_properties() -> None:
    us = MemoryUserSource("u")
    us.create_database("alice")
    assert us.list_users() == ["alice"]
    assert "name" in us.list_metadata("alice")["identity"]  # seeded from the schema


def test_file_source_keeps_the_user_beside_its_registry(tmp_path: Path) -> None:
    us = _file_source(tmp_path)
    us.create_database("bob")
    us.set_metadata("bob", "identity.name", "Bob")

    base = tmp_path / "sources" / "bob"
    assert (tmp_path / "registries" / "bob.json").is_file()
    for name in ("metadata.json", "contacts.json", "sessions.json"):
        assert (base / name).is_file()
    # What the CLI, MCP server and REST API create, so each can open the others' users.
    assert _file_source(tmp_path).get_metadata("bob", "identity.name") == "Bob"


def test_the_front_ends_layout_is_the_librarys(tmp_path: Path) -> None:
    props = _file_source(tmp_path).default_user_props("bob")
    base = tmp_path / "sources" / "bob"
    assert props["kb_source"]["connection"]["directory"] == str(base)
    assert props["doc_source"]["vector_source"]["directory"] == str(base / "sessions")


def test_given_properties_replace_one_default_each() -> None:
    us = MemoryUserSource("u")
    kb = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}
    us.create_database("carol", {"kb_source": kb})
    assert us.list_users() == ["carol"]


def test_an_existing_user_needs_overwrite(tmp_path: Path) -> None:
    us = _file_source(tmp_path)
    us.create_database("dan")
    us.set_metadata("dan", "identity.name", "Dan")

    with pytest.raises(UserExistsError):
        us.create_database("dan")
    assert us.get_metadata("dan", "identity.name") == "Dan"  # untouched

    us.create_database("dan", overwrite=True)
    assert us.get_metadata("dan", "identity.name") is None  # a fresh user


def test_registry_style_call_with_overwrite_keyword() -> None:
    """blue-data's DataRegistry.create_source_database passes properties={} and overwrite."""
    us = MemoryUserSource("u")
    assert us.create_database("erin", properties={}, overwrite=False) == {}
    assert us.list_users() == ["erin"]


def test_a_store_without_a_default_is_named() -> None:
    with pytest.raises(QueryError, match="RedisUserSource has no default for kb_source"):
        RedisUserSource("u").create_database("frank")


def test_a_bad_name_is_rejected_before_any_path_is_built(tmp_path: Path) -> None:
    with pytest.raises(QueryError, match="invalid database name"):
        _file_source(tmp_path).create_database("../escape")
    assert not (tmp_path.parent / "escape").exists()


def test_it_does_not_onboard_unless_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    us = MemoryUserSource("u")
    asked: list[str] = []

    async def onboard_user(name: str, **_: object) -> None:
        asked.append(name)

    monkeypatch.setattr(us, "onboard_user", onboard_user)
    us.create_database("gina")
    assert asked == []
    us.create_database("hal", {"onboard": True})
    assert asked == ["hal"]
