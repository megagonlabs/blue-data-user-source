"""``top_k`` caps the chunks taken from each document store per sub-question.

The CLI's ``data query --top-k`` used to send it, and the library ignored it:
every search asked for a fixed five chunks.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from blue_data_user_source import MemoryUserSource, QueryError
from blue_data_user_source.data.manager import DOC_SEARCH_TOP_K, UserDataManager
from tests.unit.doubles.sources import make_mock_kb


def _doc_source() -> MagicMock:
    return MagicMock(execute_query=MagicMock(return_value=[]))


@pytest.fixture
def doc_sources(manager: UserDataManager) -> tuple[MagicMock, MagicMock]:
    manager._kb_source = make_mock_kb(result=["result"])
    session_content, external_documents = _doc_source(), _doc_source()
    manager.ensure_session_doc_source = MagicMock(return_value=session_content)  # type: ignore[method-assign]
    manager.ensure_external_documents_source = MagicMock(return_value=external_documents)  # type: ignore[method-assign]
    return session_content, external_documents


async def test_top_k_reaches_both_document_searches(manager, doc_sources) -> None:
    await manager.execute_query("what are my skills?", top_k=12)
    for source in doc_sources:
        assert source.execute_query.call_args.args[0]["k"] == 12


async def test_default_is_unchanged(manager, doc_sources) -> None:
    await manager.execute_query("what are my skills?")
    for source in doc_sources:
        assert source.execute_query.call_args.args[0]["k"] == DOC_SEARCH_TOP_K


@pytest.mark.parametrize("bad", [0, -3, "10", 2.5, True])
async def test_a_bad_top_k_is_rejected_before_anything_runs(bad) -> None:
    us = MemoryUserSource("top-k", {"console": False})
    await us.create_user(
        "alice", registry_props={"backend": "memory"}, kb_source_props={"backend": "memory"},
        metadata_source_props={"backend": "memory"}, contact_source_props={"backend": "memory"},
        session_source_props={"backend": "memory"}, onboard=False,
    )
    with pytest.raises(QueryError, match="top_k must be a positive integer"):
        await us._run_query("what are my skills?", database="alice", optional_properties={"top_k": bad})
    assert await us.list_sessions("alice") == {}  # no session left behind
