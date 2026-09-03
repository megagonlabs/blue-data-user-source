"""Tests for UserDataManager.execute_query()."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from blue_data_user_source.data.manager import UserDataManager
from tests.unit.doubles.sources import make_mock_kb


@pytest.fixture
async def manager_with_mock_kb(manager: UserDataManager) -> UserDataManager:
    manager._kb_source = make_mock_kb(result=["result"], metadata={"n1": {"created": "2024-01-01T00:00:00+00:00", "modified": "2024-01-01T00:00:00+00:00"}})
    return manager


async def test_execute_query_returns_list_and_dict(manager_with_mock_kb: UserDataManager) -> None:
    data, metadata = await manager_with_mock_kb.execute_query("what are my skills?")
    assert isinstance(data, list)
    assert isinstance(metadata, dict)


async def test_execute_query_returns_kb_result(manager_with_mock_kb: UserDataManager) -> None:
    data, _ = await manager_with_mock_kb.execute_query("q")
    assert data == ["result"]


async def test_execute_query_returns_kb_metadata(manager_with_mock_kb: UserDataManager) -> None:
    _, metadata = await manager_with_mock_kb.execute_query("q")
    assert "n1" in metadata
    assert "created" in metadata["n1"]


async def test_execute_query_passes_include_metadata_true(manager: UserDataManager) -> None:
    mock_kb = make_mock_kb()
    manager._kb_source = mock_kb
    await manager.execute_query("q")
    mock_kb.answer.assert_awaited_once()
    call_kwargs = mock_kb.answer.call_args.kwargs
    assert call_kwargs.get("include_metadata") is True


async def test_execute_query_passes_callbacks(manager: UserDataManager) -> None:
    mock_kb = make_mock_kb()
    manager._kb_source = mock_kb
    on_call = AsyncMock()
    on_result = AsyncMock()
    await manager.execute_query("q", on_tool_call=on_call, on_tool_result=on_result)
    call_kwargs = mock_kb.answer.call_args.kwargs
    assert call_kwargs.get("on_tool_call") is on_call
    assert call_kwargs.get("on_tool_result") is on_result


async def test_execute_query_str_result_wrapped_in_dict(manager: UserDataManager) -> None:
    mock_kb = make_mock_kb(result="plain text answer")
    manager._kb_source = mock_kb
    data, _ = await manager.execute_query("q")
    assert data == [{"answer": "plain text answer"}]


async def test_execute_query_none_result_returns_empty_list(manager: UserDataManager) -> None:
    mock_kb = make_mock_kb(result=None)
    manager._kb_source = mock_kb
    data, _ = await manager.execute_query("q")
    assert data == []


async def test_execute_query_empty_metadata_when_kb_returns_none(manager: UserDataManager) -> None:
    mock_kb = make_mock_kb(result=[], metadata={})
    manager._kb_source = mock_kb
    _, metadata = await manager.execute_query("q")
    assert metadata == {}


async def test_execute_query_includes_session_content_matches(
    manager_with_mock_kb: UserDataManager,
) -> None:
    doc_source = manager_with_mock_kb.ensure_session_doc_source("s1")
    doc_source.ingest_text("Alice prefers remote work.", file_name="q1-i1.txt")

    data, metadata = await manager_with_mock_kb.execute_query("remote work")

    session_entries = [
        d for d in data if isinstance(d, dict) and d.get("source") == "session_content"
    ]
    assert session_entries
    assert any("remote work" in e["text"] for e in session_entries)
    assert any(m.get("source") == "session_content" for m in metadata.values())


async def test_execute_query_includes_external_document_matches(
    manager_with_mock_kb: UserDataManager, tmp_path,
) -> None:
    f = tmp_path / "resume.txt"
    f.write_text("Alice knows Python and SQL.\n")
    await manager_with_mock_kb.add_source(f)

    data, metadata = await manager_with_mock_kb.execute_query("Python")

    external_entries = [
        d for d in data if isinstance(d, dict) and d.get("source") == "external_documents"
    ]
    assert external_entries
    assert any(m.get("source") == "external_documents" for m in metadata.values())


async def test_execute_query_still_returns_kb_result_alongside_doc_matches(
    manager_with_mock_kb: UserDataManager,
) -> None:
    data, _ = await manager_with_mock_kb.execute_query("q")
    assert "result" in data
