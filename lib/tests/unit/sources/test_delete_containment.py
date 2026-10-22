"""Delete and reset remove files only inside the user data directory (#156).

A store's recorded path may come from another tool, an older version or a shared
registry, so a path outside the data directory, or one that leaves it through a
symlink, is refused (logged, and returned to the caller) rather than deleted.
Each path is checked with blue-data's ``contain()``.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from blue_data_user_source import FileUserSource, MemoryUserSource
from blue_data_user_source.data.manager import CLS_JSON_FILE, CLS_KB_MEMORY

_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}


def _json_file(path: Path) -> dict:
    return {"_class": CLS_JSON_FILE, "connection": {"protocol": "json/file", "path": str(path)}}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    victim_dir = tmp_path / "elsewhere"
    victim_dir.mkdir()
    return victim_dir


def _source(data_dir: Path) -> FileUserSource:
    return FileUserSource("u", {"connection": {"path": str(data_dir / "registry.json")}})


def test_a_normal_delete_still_removes_everything(data_dir: Path) -> None:
    us = _source(data_dir)
    us.create_database("alice")
    us.set_metadata("alice", "identity.name", "Alice")
    assert asyncio.run(us.delete_user("alice")) == []
    assert not (data_dir / "registries" / "alice.json").exists()
    assert not list((data_dir / "sources").glob("alice/*.json"))


def test_a_recorded_path_outside_the_data_directory_is_kept(
    data_dir: Path, outside: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    victim = outside / "metadata.json"
    us = _source(data_dir)
    # A record as another tool might have written it: the metadata store points elsewhere.
    us.create_database("bob", {"metadata_source": _json_file(victim)})
    us.set_metadata("bob", "identity.name", "Bob")
    assert victim.exists()

    with caplog.at_level(logging.WARNING):
        refused = asyncio.run(us.delete_user("bob"))

    assert victim.exists()
    assert refused == [str(victim)]
    assert "outside the data directory" in caplog.text
    assert not (data_dir / "registries" / "bob.json").exists()  # what is inside still goes
    assert "bob" not in us.list_users()


def test_a_symlink_out_of_the_data_directory_is_refused(data_dir: Path, outside: Path) -> None:
    victim = outside / "contacts.json"
    data_dir.mkdir(parents=True)
    (data_dir / "link").symlink_to(outside, target_is_directory=True)
    us = _source(data_dir)
    us.create_database("carol", {"contact_source": _json_file(data_dir / "link" / "contacts.json")})
    asyncio.run(us.add_contact_method("carol", "email", "work", {"address": "c@example.com"}))
    assert victim.exists()

    refused = asyncio.run(us.delete_user("carol"))

    assert victim.exists()
    assert refused == [str(data_dir / "link" / "contacts.json")]


def test_reset_keeps_a_document_store_recorded_outside(data_dir: Path, outside: Path) -> None:
    sessions_dir = outside / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "documents.json").write_text("{}")
    (outside / "external_documents").mkdir()
    (outside / "external_documents" / "keep.json").write_text("{}")
    us = _source(data_dir)
    us.create_database("dan", {
        "doc_source": {"embedding_model": "dummy",
                       "vector_source": {"backend": "file", "directory": str(sessions_dir)}},
    })

    refused = asyncio.run(us.reset_user("dan"))

    assert (sessions_dir / "documents.json").exists()
    assert (outside / "external_documents" / "keep.json").exists()
    assert str(sessions_dir) in refused and str(outside / "external_documents") in refused


def test_a_source_without_a_data_directory_deletes_no_files(tmp_path: Path) -> None:
    victim = tmp_path / "metadata.json"
    us = MemoryUserSource("u")
    us.create_database("erin", {"metadata_source": _json_file(victim)})
    us.set_metadata("erin", "identity.name", "Erin")

    assert asyncio.run(us.delete_user("erin")) == [str(victim)]
    assert victim.exists()


def test_the_file_layout_is_composed_with_contain(data_dir: Path) -> None:
    """A symlinked data directory resolves; the composed paths stay inside it."""
    real = data_dir.parent / "real"
    real.mkdir(parents=True)
    data_dir.symlink_to(real, target_is_directory=True)
    props = _source(data_dir).default_user_props("frank")
    assert Path(props["registry"]["connection"]["path"]) == real / "registries" / "frank.json"
    assert Path(props["kb_source"]["connection"]["directory"]) == real / "sources" / "frank"
