"""Tests for blue-data-user-mcp tool functions.

Each test injects a pre-built in-memory MemoryUserSource as the server
singleton so no file I/O, network access, or OPENAI_API_KEY is needed
(except the query test, which mocks the reasoning layer).
"""
from __future__ import annotations

import io
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
        session_source_props=_MEMORY_REGISTRY,
        # `create_user` onboards by default, which prompts on stdin — see the
        # module docstring: these tests need no input, network, or API key.
        onboard=False,
        onboard_metadata=False,
    )
    return inst


class _RefusingStdin(io.StringIO):
    """A stdin that fails loudly instead of quietly returning EOF.

    An empty stream would let a prompt "succeed" with a blank answer, which is
    how #107 stayed invisible: the interactive path ran, read nothing, and the
    test failed later for an unrelated-looking reason.
    """

    def _refuse(self, *args, **kwargs):
        raise AssertionError(
            "the server prompted for input — nothing in this suite may read stdin"
        )

    read = readline = readlines = __next__ = _refuse


@pytest.fixture(autouse=True)
def no_stdin(monkeypatch):
    """Nothing reachable from an MCP tool may prompt: a server has no console."""
    monkeypatch.setattr("sys.stdin", _RefusingStdin())
    monkeypatch.setattr("builtins.input", _RefusingStdin()._refuse)


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


async def test_delete_database_reports_paths_it_kept(source, tmp_path):
    """A recorded file outside the data directory is not deleted, and the tool says so (#156)."""
    victim = tmp_path / "metadata.json"
    source.create_database("kept", {"metadata_source": {
        "_class": "blue_data.source.json.file_json_source.FileJSONSource",
        "connection": {"protocol": "json/file", "path": str(victim)},
    }})
    source.set_metadata("kept", "identity.name", "K")
    result = json.loads(await delete_database("kept"))
    assert result["deleted"] is True
    assert result["not_deleted"] == [str(victim)]
    assert victim.exists()


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
        config_module.get_source(), "async_execute_query",
        new=AsyncMock(return_value=(mock_result, "sess-1")),
    ):
        from blue_data_user_mcp.server import query
        result = json.loads(await query(USER, "What skills does alice have?"))
    assert result == {"results": mock_result, "session_id": "sess-1"}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

async def test_add_source_type1_no_queries(tmp_path):
    resume = tmp_path / "resume.txt"
    resume.write_text("Alice has ten years of Python experience.")
    result = json.loads(await add_source(USER, str(resume), name="resume"))
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


async def test_remove_source_removes_a_registered_source(tmp_path):
    """The guard on the unknown case must not block the real one."""
    resume = tmp_path / "resume.txt"
    resume.write_text("Alice has ten years of Python experience.")
    await add_source(USER, str(resume), name="resume")

    result = json.loads(await remove_source(USER, "resume"))
    assert result["removed"] is True
    assert result["chunks_removed"] >= 1
    assert "resume" not in [s.get("name") for s in json.loads(await list_sources(USER))]


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


async def test_create_database_rejects_a_name_that_is_not_a_path_segment():
    """#146: the library rejects it before writing anything; the tool reports it."""
    result = json.loads(await create_database(".."))
    assert "invalid database name" in result["error"]


async def test_contact_tools_mask_secrets():
    """What a tool returns lands in the LLM's context, so secrets are masked (#143)."""
    await add_contact(USER, "email", "work", {"address": "a@example.com", "smtp_password": "hunter2"})
    got = json.loads(await get_contact(USER, "email", "work"))
    listed = await list_contacts(USER)
    assert got["details"]["smtp_password"] == "***"
    assert got["details"]["address"] == "a@example.com"
    assert "hunter2" not in listed


async def test_every_tool_parameter_is_described_in_its_schema():
    """#105: clients see only the schema; the docstrings' Args: never reached it."""
    from blue_data_user_mcp.server import mcp

    tools = await mcp.list_tools()
    assert len(tools) == 23
    for tool in tools:
        for param, schema in tool.inputSchema.get("properties", {}).items():
            assert schema.get("description"), f"{tool.name}.{param} has no description"
    by_name = {t.name: t for t in tools}
    assert by_name["query"].inputSchema["properties"]["output_form"]["enum"] == ["json", "nl"]
    optional = by_name["list_contacts"].inputSchema["properties"]["protocol"]["anyOf"]
    assert {"type": "null"} in optional and any("enum" in branch for branch in optional)
