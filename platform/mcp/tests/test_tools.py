"""Tests for blue-data-user-mcp tool functions.

Each test injects a pre-built in-memory MemoryUserSource as the server
singleton so no file I/O, network access, or OPENAI_API_KEY is needed
(except the query test, which mocks the reasoning layer).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from blue_data_user_source import MemoryUserSource
from blue_data_user_source.data.manager import CLS_JSON_MEMORY

import blue_data_user_mcp.config as config_module
from blue_data_user_mcp.server import (
    add_contact,
    add_source,
    create_database,
    delete_database,
    get_contact,
    get_database,
    get_metadata,
    list_contacts,
    list_data,
    list_databases,
    list_metadata,
    list_sources,
    remove_contact,
    remove_source,
    reset_database,
    set_metadata,
    update_contact,
)

USER = "alice"

_MEMORY_REGISTRY = {
    "_class": CLS_JSON_MEMORY,
    "connection": {"protocol": "json/memory"},
}
_MEMORY_KB = {
    "_class": "blue_data_kb_source.memory_kb_source.MemoryKBSource",
    "connection": {"protocol": "kb/memory"},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def source():
    inst = MemoryUserSource(name="test-user-source")
    await inst.create_user(
        USER,
        registry_props=_MEMORY_REGISTRY,
        kb_source_props=_MEMORY_KB,
        metadata_source_props=_MEMORY_REGISTRY,
        contact_source_props=_MEMORY_REGISTRY,
    )
    return inst


@pytest.fixture(autouse=True)
def inject_source(source, tmp_path):
    config_module._source = source
    config_module._data_dir = tmp_path
    yield
    config_module.reset_source()


# ---------------------------------------------------------------------------
# Users (write)
# ---------------------------------------------------------------------------

async def test_create_database_new_user():
    result = json.loads(await create_database("bob"))
    assert result["created"] is True
    assert result["name"] == "bob"


async def test_create_database_already_exists_returns_error():
    result = json.loads(await create_database(USER))
    assert "error" in result


async def test_delete_database_removes_user():
    result = json.loads(await delete_database(USER))
    assert result["deleted"] is True
    users = json.loads(await list_databases())
    assert USER not in users


async def test_reset_database_returns_ok():
    result = json.loads(await reset_database(USER))
    assert result["reset"] is True


# ---------------------------------------------------------------------------
# Users (read)
# ---------------------------------------------------------------------------

async def test_list_databases_contains_user():
    result = json.loads(await list_databases())
    assert USER in result


async def test_get_database_returns_info():
    result = json.loads(await get_database(USER))
    assert result["name"] == USER


async def test_get_database_unknown_returns_error():
    result = json.loads(await get_database("nobody"))
    assert "error" in result


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

async def test_query_returns_results():
    mock_result = [{"query": "test", "results": []}]
    with patch.object(
        config_module.get_source(), "async_execute_query", new=AsyncMock(return_value=mock_result)
    ):
        from blue_data_user_mcp.server import query
        result = json.loads(await query(USER, "What skills does alice have?"))
    assert result == mock_result


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

async def test_add_source_type1_no_queries():
    result = json.loads(await add_source(USER, "resume.txt", name="resume"))
    assert result["added"] is True


async def test_list_data_returns_list():
    result = json.loads(await list_data(USER))
    assert isinstance(result, list)


async def test_list_sources_returns_list():
    result = json.loads(await list_sources(USER))
    assert isinstance(result, list)


async def test_remove_source_unknown_returns_error():
    result = json.loads(await remove_source(USER, "nonexistent"))
    assert "error" in result


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

async def test_set_and_get_metadata():
    result = json.loads(await set_metadata(USER, "preferences.verbosity", "brief"))
    assert result["value"] == "brief"

    got = json.loads(await get_metadata(USER, "preferences.verbosity"))
    assert got["value"] == "brief"


async def test_list_metadata_returns_dict():
    await set_metadata(USER, "identity.name", "Alice")
    result = json.loads(await list_metadata(USER))
    assert isinstance(result, dict)


async def test_get_metadata_missing_returns_error():
    result = json.loads(await get_metadata(USER, "does.not.exist"))
    assert "error" in result


async def test_delete_metadata():
    await set_metadata(USER, "skills", ["python"])
    from blue_data_user_mcp.server import delete_metadata as _del
    r = json.loads(await _del(USER, "skills"))
    assert r["deleted"] is True


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

async def test_add_and_list_contact():
    result = json.loads(await add_contact(
        USER, "email", "work", {"address": "alice@example.com"}, preference=1
    ))
    assert result["added"] is True

    contacts = json.loads(await list_contacts(USER, protocol="email"))
    assert isinstance(contacts, list)
    assert any(c.get("name") == "work" for c in contacts)


async def test_get_contact_returns_details():
    await add_contact(USER, "email", "home", {"address": "alice@home.com"})
    result = json.loads(await get_contact(USER, "email", "home"))
    assert result.get("name") == "home"


async def test_get_contact_missing_returns_error():
    result = json.loads(await get_contact(USER, "email", "nonexistent"))
    assert "error" in result


async def test_update_contact():
    await add_contact(USER, "email", "work", {"address": "alice@example.com"})
    result = json.loads(await update_contact(USER, "email", "work", preference=5))
    assert result["updated"] is True


async def test_remove_contact():
    await add_contact(USER, "email", "temp", {"address": "tmp@example.com"})
    result = json.loads(await remove_contact(USER, "email", "temp"))
    assert result["removed"] is True
