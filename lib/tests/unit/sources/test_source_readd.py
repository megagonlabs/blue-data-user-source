"""Adding a source that is already registered updates it, instead of adding a second (#176).

The guide's walkthrough adds the same file as Type 1 (register) and then Type 2
(register and extract). That created two SOURCE nodes with the same name, put the
file's chunks into the document store twice, and the guide's next step,
``remove_source`` by name, raised. Extraction is stubbed: these tests are offline.
"""
from __future__ import annotations

import os
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


# ── what counts as the same source (#196) ─────────────────────────────────────

def _found(us: FileUserSource, word: str) -> bool:
    return any(word in (c["text"] or "") for c in _chunks(us, word))


async def test_different_nameless_texts_are_different_sources(us) -> None:
    assert await us.add_text_source("Alice speaks fluent Japanese.", "alice") is False
    assert await us.add_text_source("Alice keeps bees in Lisbon.", "alice") is False
    assert len(await us.list_sources("alice")) == 2
    assert _found(us, "Japanese") and _found(us, "bees")


async def test_the_same_nameless_text_is_one_source_and_stays_searchable(us) -> None:
    await us.add_text_source("Alice speaks fluent Japanese.", "alice")
    assert await us.add_text_source("Alice speaks fluent Japanese.", "alice") is True
    assert len(await us.list_sources("alice")) == 1
    assert _found(us, "Japanese")


async def test_named_text_is_replaced_by_its_name(us) -> None:
    await us.add_text_source("Alice speaks fluent Japanese.", "alice", {"name": "note"})
    assert await us.add_text_source("Alice keeps bees in Lisbon.", "alice", {"name": "note"}) is True
    [source] = await us.list_sources("alice")
    assert source["source"] == "text:note"
    assert _found(us, "bees") and not _found(us, "Japanese")


async def test_one_relative_name_from_two_directories_is_two_sources(us, tmp_path, monkeypatch) -> None:
    for directory, text in (("a", "Alice owns a red canoe."), ("b", "Alice plays the cello.")):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "notes.txt").write_text(text)
        monkeypatch.chdir(tmp_path / directory)
        await us.add_source("notes.txt", "alice")
    assert sorted(s["source"] for s in await us.list_sources("alice")) == [
        str(tmp_path / "a" / "notes.txt"), str(tmp_path / "b" / "notes.txt"),
    ]
    assert _found(us, "canoe") and _found(us, "cello")


async def test_one_file_by_two_spellings_is_one_source(us, tmp_path, monkeypatch) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "notes.txt").write_text("Alice owns a red canoe.")
    monkeypatch.chdir(tmp_path)
    await us.add_source("a/notes.txt", "alice")
    assert await us.add_source(f".{os.sep}a{os.sep}notes.txt", "alice") is True
    [source] = await us.list_sources("alice")
    assert source["name"] == "a/notes.txt"  # removable by the name it was added under
    assert (await us.remove_source("alice", "a/notes.txt"))["id"] == source["id"]


async def test_a_failed_re_add_keeps_the_old_document(us, tmp_path) -> None:
    gone = tmp_path / "gone.txt"
    gone.write_text("Alice was born in Porto.")
    await us.add_source(str(gone), "alice")
    gone.unlink()
    with pytest.raises(FileNotFoundError):
        await us.add_source(str(gone), "alice")
    assert _found(us, "Porto")
    await us.remove_source("alice", str(gone))  # and it is still recorded
    assert not _found(us, "Porto")


async def test_a_failed_first_add_leaves_no_source(us, tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        await us.add_source(str(tmp_path / "missing.txt"), "alice")
    assert await us.list_sources("alice") == []


async def test_re_adding_an_unchanged_file_keeps_its_chunks_and_record(us, resume) -> None:
    await us.add_source(str(resume), "alice")
    await us.add_source(str(resume), "alice")
    assert _found(us, "Python")
    assert (await us.remove_source("alice", str(resume)))["chunks_removed"] >= 1
    assert not _found(us, "Python")

