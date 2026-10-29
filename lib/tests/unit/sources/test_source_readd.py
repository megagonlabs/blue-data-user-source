"""Adding a source that is already registered updates it, instead of adding a second (#176).

The guide's walkthrough adds the same file as Type 1 (register) and then Type 2
(register and extract). That created two SOURCE nodes with the same name, put the
file's chunks into the document store twice, and the guide's next step,
``remove_source`` by name, raised. Extraction is stubbed: these tests are offline.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from blue_data_user_source import FileUserSource

_OFFLINE = {"doc_embedding_model": "dummy", "doc_search_mode": "bm25"}


@pytest.fixture
def us(tmp_path: Path) -> FileUserSource:
    source = FileUserSource("us", {"connection": {"path": str(tmp_path / "data" / "registry.json")}, "console": False})
    source.create_database("alice", _OFFLINE)
    return source


@pytest.fixture
def resume(tmp_path: Path) -> Path:
    path = tmp_path / "resume.txt"
    path.write_text("Alice Example\nSenior Project Manager at Example Corp.\nSkills: Python, SQL.\n")
    return path


@pytest.fixture
def import_text(us: FileUserSource):
    stub = AsyncMock()
    with patch.object(us._get_manager("alice")._ensure_kb_source(), "import_text", stub):
        yield stub


def _chunks(us: FileUserSource, query: str) -> list[dict]:
    manager = us._get_manager("alice")
    source = manager.ensure_external_documents_source()
    return manager._search_doc_source(source, query, "external_documents", {}, 10)


async def test_type_1_then_type_2_leaves_one_source(us, resume, import_text) -> None:
    await us.add_source(str(resume), database="alice")
    [first] = await us.list_sources("alice")

    await us.add_source(str(resume), database="alice",
                        optional_properties={"queries": ["What skills does the user have?"]})

    assert await us.list_sources("alice") == [first]
    assert import_text.await_args.kwargs["source_id"] == first["id"]  # extracted into it
    assert len([c for c in _chunks(us, "Python") if "Python" in (c["text"] or "")]) == 1  # not twice

    removed = await us.remove_source("alice", first["name"])  # the guide's next step
    assert removed["id"] == first["id"]
    assert await us.list_sources("alice") == []


async def test_a_changed_file_replaces_its_chunks(us, resume, import_text) -> None:
    await us.add_source(str(resume), database="alice")
    resume.write_text("Alice Example\nSkills: Haskell.\n")
    await us.add_source(str(resume), database="alice")

    assert len(await us.list_sources("alice")) == 1
    assert any("Haskell" in (c["text"] or "") for c in _chunks(us, "Haskell"))
    assert not any("Python" in (c["text"] or "") for c in _chunks(us, "Python"))


async def test_the_same_file_under_another_name_is_another_source(us, resume, import_text) -> None:
    await us.add_source(str(resume), database="alice", optional_properties={"name": "resume-2025"})
    await us.add_source(str(resume), database="alice", optional_properties={"name": "resume-2026"})
    assert sorted(s["name"] for s in await us.list_sources("alice")) == ["resume-2025", "resume-2026"]
