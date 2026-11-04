"""A store's password is recorded as the name of its environment variable (#194).

blue-data strips passwords from what it stores, so a user created with one could
not be reopened by any later process. These tests are offline: a second source
object stands for the later process, and the real-server check is in the issue.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from blue_data_user_source import FileUserSource, QueryError, RedisUserSource
from blue_data_user_source.data.manager import (
    CLS_JSON_MEMORY,
    CLS_KB_MEMORY,
    UserDataManager,
    _build_json_source,
    _with_env_password,
    require_password_references,
    without_passwords,
)

_ENV = "DEMO_STORE_PASSWORD"


def _memory() -> dict:
    return {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}


def test_a_reference_supplies_the_password_and_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "from-env")
    assert _with_env_password({"password_env": _ENV}) == {"password_env": _ENV, "password": "from-env"}


def test_a_password_given_beside_the_reference_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    connection = {"password": "given", "password_env": _ENV}
    assert _with_env_password(connection) == connection


def test_an_unset_reference_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    with pytest.raises(ValueError, match=rf"\${_ENV}"):
        _with_env_password({"password_env": _ENV})


def test_the_later_process_names_the_missing_variable_before_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    manager = UserDataManager("alice", _memory())
    manager._registry = MagicMock()
    manager._registry.get_source_properties.return_value = {"connection": {"password_env": _ENV}}
    with pytest.raises(ValueError, match=rf"\${_ENV}"):
        manager._ensure_kb_source()
    manager._registry.connect_source.assert_not_called()


def test_a_json_store_is_built_with_the_password_and_records_the_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "from-env")
    props = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory", "password_env": _ENV}}
    source = _build_json_source("metadata", props)
    assert source.properties["connection"]["password"] == "from-env"
    assert source.properties["connection"]["password_env"] == _ENV


def test_without_passwords_removes_only_passwords() -> None:
    props = {"connection": {"password": "p", "password_env": _ENV}, "max_tokens": 5, "stores": [{"password": "p"}]}
    assert without_passwords(props) == {"connection": {"password_env": _ENV}, "max_tokens": 5, "stores": [{}]}


@pytest.mark.parametrize("props", [
    {"connection": {"password": "p"}},
    [{"connection": {"password": "p"}}],
    {"vector_source": {"connection": {"password": "p"}}},
])
def test_a_password_without_a_reference_is_refused(props: Any) -> None:
    with pytest.raises(QueryError, match="password_env"):
        require_password_references(props)


@pytest.mark.parametrize("props", [
    {"connection": {"password": "p", "password_env": _ENV}},
    {"connection": {"password_env": _ENV}},
    {"connection": {"password": ""}},
    {"connection": {}},
])
def test_stores_with_a_reference_or_no_password_are_accepted(props: Any) -> None:
    require_password_references(props)


async def test_create_user_refuses_before_writing_anything(tmp_path: Path) -> None:
    source = FileUserSource("us", {"connection": {"path": str(tmp_path / "registry.json")}})
    props = source.default_user_props("alice")
    kb = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory", "password": "p"}}
    with pytest.raises(QueryError, match="password_env"):
        await source.create_user("alice", props["registry"], kb, props["metadata_source"], props["contact_source"],
                                 props["session_source"], onboard=False)
    assert source.get_user("alice") is None


def _redis(**connection: Any) -> RedisUserSource:
    # The source's own registry in memory, so no Redis is needed.
    return RedisUserSource("us", {"connection": connection, "registry": _memory()})


def test_the_outer_records_hold_no_password() -> None:
    source = _redis(password="clear-text", password_env=_ENV)
    assert "clear-text" not in json.dumps(source._registry.get_source_record("us"))


def test_reopening_the_source_records_no_password() -> None:
    source = _redis(password="clear-text", password_env=_ENV)
    with patch.object(source._registry, "set_source_property") as stored:
        source.__init__("us", {"connection": {"password": "clear-text", "password_env": _ENV}, "registry": _memory()})
    assert "clear-text" not in str(stored.mock_calls)


def test_a_redis_users_stores_all_carry_the_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV, "from-env")
    source = _redis(password_env=_ENV)
    source.properties["registry"] = {"connection": {"protocol": "json/redis", "password_env": _ENV}, "namespace": "n"}
    stores = source.default_user_props("alice")
    assert {s["connection"]["password_env"] for s in stores.values()} == {_ENV}
