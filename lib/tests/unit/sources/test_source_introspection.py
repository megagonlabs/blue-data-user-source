"""Tests for UserSource's schema/entity/relation introspection, stats, and
generic NL2Q tool support (#25).

These are plain sync tests (not ``async def``): the ``UserSource`` methods under
test are themselves synchronous and internally use ``asyncio.run`` (matching
the existing pattern in ``execute_query``/``create_database``), which cannot
be called from within a running event loop — i.e. not from an ``async def``
test under pytest-asyncio's auto mode. Async setup calls are driven explicitly
via ``asyncio.run`` instead.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from blue_data_user_source.data.manager import CLS_JSON_MEMORY, CLS_KB_MEMORY
from blue_data_user_source.memory_user_source import MemoryUserSource
from blue_data_user_source.source import _DEFAULT_SCHEMA_PATH

_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}


def _create_user_kwargs(**overrides) -> dict:
    kwargs = {
        "registry_props": _MEM_JSON,
        "kb_source_props": _MEM_KB,
        "metadata_source_props": _MEM_JSON,
        "contact_source_props": _MEM_JSON,
        "session_source_props": _MEM_JSON,
        "onboard": False,
    }
    kwargs.update(overrides)
    return kwargs


def _make_user(name: str = "alice") -> MemoryUserSource:
    source = MemoryUserSource()
    asyncio.run(source.create_user(name, **_create_user_kwargs()))
    return source


def _set_person_name(source: MemoryUserSource, database: str, first: str, last: str) -> None:
    asyncio.run(source._get_manager(database).set_person_name(first, last))


# ── schema / entity / relation introspection ──────────────────────────────────

def test_fetch_metadata_reports_user_count_and_schema_paths() -> None:
    source = _make_user()
    meta = source.fetch_metadata()
    assert meta["user_count"] == 1
    assert meta["schema"] == _DEFAULT_SCHEMA_PATH


def test_fetch_schema_returns_template_schema() -> None:
    source = MemoryUserSource()
    schema = source.fetch_schema()
    assert "PERSON" in schema["entities"]


def test_fetch_database_schema_matches_kb_export() -> None:
    source = _make_user()
    schema = source.fetch_database_schema("alice")
    assert "PERSON" in schema["entities"]
    assert "relations" in schema


def test_fetch_database_collection_entities_only_for_kb() -> None:
    source = _make_user()
    entities = source.fetch_database_collection_entities("alice", "kb")
    assert "PERSON" in entities
    assert source.fetch_database_collection_entities("alice", "metadata") == {}


def test_fetch_database_collection_relations_only_for_kb() -> None:
    source = _make_user()
    relations = source.fetch_database_collection_relations("alice", "kb")
    assert isinstance(relations, dict)
    assert source.fetch_database_collection_relations("alice", "contacts") == {}


# ── stats ──────────────────────────────────────────────────────────────────

def test_fetch_source_stats_counts_users() -> None:
    source = _make_user("alice")
    asyncio.run(source.create_user("bob", **_create_user_kwargs()))
    assert source.fetch_source_stats() == {"user_count": 2}


def test_fetch_database_stats_unknown_user_returns_none() -> None:
    source = MemoryUserSource()
    assert source.fetch_database_stats("nobody") is None


def test_fetch_database_stats_includes_all_collections() -> None:
    source = _make_user()
    stats = source.fetch_database_stats("alice")
    assert set(stats["collections"]) >= {"kb", "metadata", "contacts", "sessions"}
    assert all(c in stats for c in ("kb", "metadata", "contacts", "sessions"))


def test_fetch_collection_stats_kb_counts_entities_and_facts() -> None:
    source = _make_user()
    _set_person_name(source, "alice", "Alice", "Smith")

    stats = source.fetch_collection_stats("alice", "kb")
    assert stats["entity_count"] == 1
    assert stats["entities_by_class"] == {"USER": 1}
    assert stats["fact_count"] == 0


def test_fetch_collection_stats_metadata_counts_set_keys() -> None:
    source = _make_user()
    source._get_manager("alice").set_metadata("identity.name", "Alice")

    stats = source.fetch_collection_stats("alice", "metadata")
    assert stats["keys_set"] == 1


def test_fetch_collection_stats_contacts_counts_methods() -> None:
    source = _make_user()
    asyncio.run(
        source.add_contact_method("alice", "email", "primary", {"address": "alice@example.com"})
    )

    stats = source.fetch_collection_stats("alice", "contacts")
    assert stats["methods"] == 1


def test_fetch_collection_stats_sessions_counts_sessions() -> None:
    source = _make_user()
    asyncio.run(source.create_session("alice"))

    stats = source.fetch_collection_stats("alice", "sessions")
    assert stats["sessions"] == 1


def test_fetch_entity_stats_counts_instances_and_properties() -> None:
    source = _make_user()
    _set_person_name(source, "alice", "Alice", "Smith")

    stats = source.fetch_entity_stats("alice", "kb", "USER")
    assert stats["count"] == 1
    assert stats["properties"] == {"FIRST_NAME": 1, "LAST_NAME": 1}


def test_fetch_entity_stats_sample_limit() -> None:
    source = _make_user()
    _set_person_name(source, "alice", "Alice", "Smith")

    stats = source.fetch_entity_stats("alice", "kb", "USER", sample_limit=5)
    assert stats["sample"] == ["Alice"]


def test_fetch_entity_stats_non_kb_collection_returns_none() -> None:
    source = _make_user()
    assert source.fetch_entity_stats("alice", "metadata", "PERSON") is None


def test_fetch_property_stats_counts_values() -> None:
    source = _make_user()
    _set_person_name(source, "alice", "Alice", "Smith")

    stats = source.fetch_property_stats("alice", "kb", "USER", "FIRST_NAME")
    assert stats["count"] == 1
    assert stats["distinct_count"] == 1
    assert stats["null_count"] == 0
    assert "sample_values" not in stats  # omitted without sample_limit


# ── generic NL2Q tools ─────────────────────────────────────────────────────

def test_get_nl_tools_rewords_execute_query_for_no_native_language() -> None:
    source = MemoryUserSource()
    tools = source.get_nl_tools()
    execute_query_tool = next(t for t in tools if t["name"] == "execute_query")
    assert "no separate native query language" in execute_query_tool["description"]


def test_execute_nl_tool_execute_query_unwraps_session_id() -> None:
    source = MemoryUserSource()
    with patch.object(
        source, "execute_query", return_value=([{"answer": "Alice"}], "session-1")
    ) as mock_exec:
        result = source.execute_nl_tool(
            "execute_query", {"query": "what is the user's name?"}, database="alice",
        )
    mock_exec.assert_called_once_with(
        "what is the user's name?", database="alice", collection=None, optional_properties=None,
    )
    assert result == [{"answer": "Alice"}]


def test_execute_nl_tool_get_sample_passes_sample_size() -> None:
    source = _make_user()
    _set_person_name(source, "alice", "Alice", "Smith")

    result = source.execute_nl_tool(
        "get_sample", {"entity": "USER", "sample_size": 1}, database="alice", collection="kb",
    )
    assert result["sample"] == ["Alice"]


def test_execute_nl_tool_get_column_stats() -> None:
    source = _make_user()
    _set_person_name(source, "alice", "Alice", "Smith")

    result = source.execute_nl_tool(
        "get_column_stats",
        {"entity": "USER", "column": "FIRST_NAME"},
        database="alice", collection="kb",
    )
    assert result["count"] == 1


def test_execute_nl_tool_unknown_tool_raises() -> None:
    source = MemoryUserSource()
    with pytest.raises(ValueError):
        source.execute_nl_tool("nonexistent", {}, database="alice")
