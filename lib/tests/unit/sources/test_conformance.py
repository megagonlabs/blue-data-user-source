"""UserSource meets blue-data's DataSource contract (design/14): its conformance kit (#164).

The kit's structural checks run as they come. Its behavioural checks run a real
query through the reasoning pipeline, with the LLM and the KB's answering agent
stubbed (unit tests are offline). The tests after the kit cover what it does not:
every output form becomes rows, the sync methods work inside a running event loop,
and the NL-tool dispatch takes the contract's full signature.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from blue_data.testing.conformance import DataSourceConformance

from blue_data_user_source import FileUserSource, MemoryUserSource, UserSource
from blue_data_user_source.data.manager import UserDataManager

_ROWS = [{"skill": "Python"}, {"skill": "SQL"}]


async def _fake_llm(prompt: str, *args: Any, properties: dict | None = None, **kwargs: Any) -> Any:
    if (properties or {}).get("response_format") == "json_object":
        # Every metric passes, expansion adds nothing, synthesis returns the table.
        return {"score": 1.0, "reasoning": "stub", "questions": [], "rows": _ROWS}
    return "What skills does Alice have?"


@pytest.fixture(autouse=True)
def _offline() -> Iterator[None]:
    answer = AsyncMock(return_value=([{"skill": "Python"}], {}))
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", _fake_llm), \
         patch.object(UserDataManager, "execute_query", answer):
        yield


def _with_user(source: UserSource) -> UserSource:
    source.create_database("alice")
    return source


class TestMemoryUserSourceConformance(DataSourceConformance):
    @pytest.fixture
    def data_source(self) -> UserSource:
        return _with_user(MemoryUserSource("conformance", {"console": False}))

    @pytest.fixture
    def sample_query(self) -> tuple[str, dict]:
        return ("what are my skills?", {"database": "alice"})


class TestFileUserSourceConformance(DataSourceConformance):
    @pytest.fixture
    def data_source(self, tmp_path: Path) -> UserSource:
        props = {"connection": {"path": str(tmp_path / "registry.json")}, "console": False}
        return _with_user(FileUserSource("conformance", props))

    @pytest.fixture
    def sample_query(self) -> tuple[str, dict]:
        return ("what are my skills?", {"database": "alice"})


# ── list[dict] in every output form (§1, #167) ───────────────────────────────

@pytest.fixture
def source() -> UserSource:
    return _with_user(MemoryUserSource("u", {"console": False}))


def test_json_answer_is_the_rows(source: UserSource) -> None:
    assert source.execute_query("what are my skills?", database="alice") == _ROWS


def test_nl_answer_is_one_row(source: UserSource) -> None:
    rows = source.execute_query_nl(
        "what are my skills?", database="alice", optional_properties={"output_form": "nl"},
    )
    assert rows == [{"answer": "What skills does Alice have?"}]  # the stub's prose


def test_expanded_answer_is_one_row(source: UserSource) -> None:
    rows = source.execute_query(
        "what are my skills?", database="alice", optional_properties={"include_expanded": True},
    )
    assert len(rows) == 1 and set(rows[0]) == {"result", "expanded"}


def test_the_session_id_comes_from_the_async_api_or_the_caller(source: UserSource) -> None:
    answer, session_id = asyncio.run(source.async_execute_query("what are my skills?", database="alice"))
    assert answer == _ROWS and session_id in asyncio.run(source.list_sessions("alice"))

    chosen = asyncio.run(source.create_session("alice"))
    source.execute_query("and my jobs?", database="alice", optional_properties={"session": chosen})
    record = asyncio.run(source.get_session("alice", chosen))
    assert record is not None and len(record["queries"]) == 1


def test_registry_style_nl_call_ignores_llm_fn(source: UserSource) -> None:
    """llm_fn and schema are accepted, as DataRegistry passes them, but unused."""
    def llm_fn(prompt: str) -> str:
        raise AssertionError("llm_fn must not be called")

    rows = source.execute_query_nl(
        "what are my skills?", database="alice", collection=None, schema={}, llm_fn=llm_fn,
        optional_properties=None,
    )
    assert rows == _ROWS


# ── inside a running event loop (§6, #168) ───────────────────────────────────

def test_sync_methods_work_inside_a_running_loop() -> None:
    async def host() -> tuple[list[dict], dict, list[dict]]:
        us = MemoryUserSource("u", {"console": False})
        us.create_database("alice")  # used to raise: asyncio.run() inside a running loop
        rows = us.execute_query("what are my skills?", database="alice")
        schema = us.fetch_database_schema("alice")
        stats = us.fetch_collection_stats("alice", "kb")
        return rows, schema, [stats]

    rows, schema, _ = asyncio.run(host())
    assert rows == _ROWS
    assert "PERSON" in schema["entities"]


# ── NL-tool dispatch signature (§5, #169) ────────────────────────────────────

def test_execute_nl_tool_takes_the_contract_signature(source: UserSource) -> None:
    rows = source.execute_nl_tool(
        "execute_query", {"query": "what are my skills?"},
        database="alice", collection="kb", optional_properties=None, read_only=True,
    )
    assert rows == _ROWS


def test_entity_stats_take_row_sample_size(source: UserSource) -> None:
    stats = source.fetch_entity_stats("alice", "kb", "PERSON", row_sample_size=1)
    assert stats is not None and len(stats.get("sample", [])) <= 1
