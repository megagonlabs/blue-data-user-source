"""Processes sharing a user's document store (#210).

blue-data's ``FileVectorSource`` locks each collection and replaces its files
atomically (blue-data#272). Before that, two processes adding to one user failed
adds, lost others, and could leave ``documents.json`` unreadable. Extraction is
not asked for, so these tests are offline.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from blue_data_user_source import FileUserSource

_OFFLINE = {"doc_embedding_model": "dummy", "doc_search_mode": "bm25"}
_WRITERS = "abcd"
_ADDS = 25

_WRITER = """
import asyncio, sys
from blue_data_user_source import FileUserSource

registry, tag, adds = sys.argv[1], sys.argv[2], int(sys.argv[3])
us = FileUserSource("us", {"connection": {"path": registry}, "console": False})

async def main():
    for i in range(adds):
        name = f"note-{tag}-{i}"
        await us.add_text_source(f"{name}: the quick brown fox.", "alice", {"name": name})

asyncio.run(main())
"""


def _source(registry: Path) -> FileUserSource:
    return FileUserSource("us", {"connection": {"path": str(registry)}, "console": False})


@pytest.fixture
def registry(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "registry.json"
    _source(path).create_database("alice", _OFFLINE)
    return path


def _store(registry: Path) -> Path:
    return registry.parent / "sources" / "alice" / "external_documents" / "documents.json"


def test_processes_adding_to_one_user_keep_every_document(registry: Path) -> None:
    writers = [subprocess.Popen([sys.executable, "-c", _WRITER, str(registry), tag, str(_ADDS)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
               for tag in _WRITERS]
    outputs = [writer.communicate(timeout=120)[0] for writer in writers]

    assert [writer.returncode for writer in writers] == [0] * len(_WRITERS), outputs
    assert len(json.loads(_store(registry).read_text())) == len(_WRITERS) * _ADDS
    assert len(asyncio.run(_source(registry).list_sources("alice"))) == len(_WRITERS) * _ADDS


async def test_an_unreadable_store_is_named_in_the_error(registry: Path) -> None:
    us = _source(registry)
    await us.add_text_source("A first note.", "alice", {"name": "first"})
    store = _store(registry)
    store.write_text(store.read_text()[:10])

    with pytest.raises(ValueError, match=str(store)):
        await _source(registry).add_text_source("A second note.", "alice", {"name": "second"})


async def test_reset_takes_the_session_stores_lock_files_with_them(registry: Path) -> None:
    us = _source(registry)
    us._get_manager("alice").ensure_session_doc_source(await us.create_session("alice"))
    directory = registry.parent / "sources" / "alice" / "sessions"
    assert list(directory.glob("*.lock"))

    assert await us.reset_user("alice") == []

    assert list(directory.glob("*")) == []
