"""How a user's documents are searched: chosen at creation, recorded, used (#172, #173).

New users default to OpenAI embeddings searched by vector. The "dummy" hash
embedding used to be the default, and vector search over it returned arbitrary
chunks. A mode and an embedding can be chosen; vector or hybrid over "dummy" is
refused. These tests stay offline, so the searches that run use "dummy" with
"bm25", in the process that ingested the documents.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from blue_data_user_source import FileUserSource, MemoryUserSource, QueryError
from blue_data_user_source.data.manager import (
    DEFAULT_DOC_SOURCE_PROPS,
    UserDataManager,
    resolve_doc_search,
)

_OFFLINE = {"doc_embedding_model": "dummy", "doc_search_mode": "bm25"}


def _file_source(tmp_path: Path) -> FileUserSource:
    return FileUserSource("us", {"connection": {"path": str(tmp_path / "registry.json")}, "console": False})


def test_a_new_user_defaults_to_openai_embeddings_searched_by_vector(tmp_path: Path) -> None:
    us = _file_source(tmp_path)
    us.create_database("alice")
    doc_source = us.get_user("alice")["doc_source"]
    assert doc_source["embedding_model"] == "openai"
    assert doc_source["search_mode"] == "vector"
    assert doc_source["vector_source"]["backend"] == "file"  # the file layout is kept


def test_create_user_without_doc_source_gets_the_same_default() -> None:
    us = MemoryUserSource("u", {"console": False})
    stores = us.default_user_props("bob")
    asyncio.run(us.create_user(
        "bob",
        registry_props=stores["registry"],
        kb_source_props=stores["kb_source"],
        metadata_source_props=stores["metadata_source"],
        contact_source_props=stores["contact_source"],
        session_source_props=stores["session_source"],
        onboard=False,
    ))
    doc_source = us.get_user("bob")["doc_source"]
    assert (doc_source["embedding_model"], doc_source["search_mode"]) == ("openai", "vector")


def test_the_chosen_mode_and_embedding_are_recorded_and_keep_the_layout(tmp_path: Path) -> None:
    us = _file_source(tmp_path)
    us.create_database("carol", {"doc_search_mode": "hybrid"})
    doc_source = us.get_user("carol")["doc_source"]
    assert (doc_source["embedding_model"], doc_source["search_mode"]) == ("openai", "hybrid")
    assert doc_source["vector_source"]["directory"].endswith("sources/carol/sessions")


@pytest.mark.parametrize("mode", ["vector", "hybrid"])
def test_vector_search_over_the_dummy_embedding_is_refused(tmp_path: Path, mode: str) -> None:
    us = _file_source(tmp_path)
    with pytest.raises(QueryError, match="needs a real embedding"):
        us.create_database("dan", {"doc_embedding_model": "dummy", "doc_search_mode": mode})
    assert "dan" not in us.list_users()


@pytest.mark.parametrize("props, message", [
    ({"doc_search_mode": "fuzzy"}, "Unknown document search mode"),
    ({"doc_embedding_model": "my.module.Embedder"}, "Unknown document embedding"),
])
def test_unknown_values_are_refused(tmp_path: Path, props: dict, message: str) -> None:
    with pytest.raises(QueryError, match=message):
        _file_source(tmp_path).create_database("erin", props)


def test_dummy_without_a_mode_is_searched_by_keyword() -> None:
    assert resolve_doc_search({"embedding_model": "dummy"})["search_mode"] == "bm25"
    # A user recorded before #172 has no mode; its "dummy" store is no longer
    # searched by vector, which ranked by hash.
    assert resolve_doc_search(DEFAULT_DOC_SOURCE_PROPS)["search_mode"] == "bm25"


def test_each_search_sends_the_users_mode() -> None:
    doc_source = MagicMock()
    doc_source.execute_query.return_value = []
    for props, mode in (({"embedding_model": "openai"}, "vector"),
                        ({"embedding_model": "openai", "search_mode": "hybrid"}, "hybrid"),
                        ({"embedding_model": "dummy"}, "bm25")):
        manager = UserDataManager("u", {}, doc_source_props=props)
        manager._search_doc_source(doc_source, "q", "external_documents", {}, 5)
        assert doc_source.execute_query.call_args.args[0]["mode"] == mode


def test_the_issue_example_finds_the_note_by_keyword(tmp_path: Path) -> None:
    """#172's example: one note about Alice's languages among 30 filler notes."""
    us = _file_source(tmp_path)
    us.create_database("alice", _OFFLINE)
    notes = [f"Meeting note {i}: the quarterly budget review moved to room {100 + i}." for i in range(30)]
    notes.insert(15, "Alice speaks fluent Japanese and some Korean.")

    async def ingest() -> None:
        for i, text in enumerate(notes):
            await us.add_text_source(text, database="alice", optional_properties={"name": f"note{i}"})

    asyncio.run(ingest())
    manager = us._get_manager("alice")
    source = manager.ensure_external_documents_source()
    hits = manager._search_doc_source(source, "Japanese", "external_documents", {}, 5)
    assert any("Japanese" in (hit["text"] or "") for hit in hits)
