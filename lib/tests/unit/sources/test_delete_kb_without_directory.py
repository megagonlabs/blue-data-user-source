"""Deleting a user empties a KB that has no directory, such as Neo4j (#201).

Only a file KB used to be cleared, so a Neo4j user's graph outlived the deletion
and a new user of the same name inherited it. A memory KB stands in here: it has
no directory either. The check on a real server is in the issue.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from blue_data_user_source import FileUserSource, UDbError
from blue_data_user_source.data.manager import CLS_KB_MEMORY

_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}


@pytest.fixture
def us(tmp_path: Path) -> FileUserSource:
    source = FileUserSource("us", {"connection": {"path": str(tmp_path / "registry.json")}, "console": False})
    source.create_database("alice", {"kb_source": _KB, "doc_embedding_model": "dummy", "doc_search_mode": "bm25"})
    return source


async def test_delete_empties_the_kb_through_the_kb_itself(us: FileUserSource) -> None:
    kb = MagicMock()
    with patch.object(us._get_manager("alice"), "_ensure_kb_source", return_value=kb):
        assert await us.delete_user("alice") == []
    kb.create_database.assert_called_once_with("alice", overwrite=True)
    assert us.get_user("alice") is None


async def test_a_kb_that_cannot_be_cleared_leaves_the_user_in_place(us: FileUserSource, tmp_path: Path) -> None:
    us.set_metadata("alice", "identity.name", "Alice")
    kb = MagicMock()
    kb.create_database.side_effect = ConnectionError("server down")
    with patch.object(us._get_manager("alice"), "_ensure_kb_source", return_value=kb), \
            pytest.raises(UDbError, match="nothing was deleted.*server down"):
        await us.delete_user("alice")
    assert us.get_user("alice") is not None
    assert us.get_metadata("alice", "identity.name") == "Alice"


async def test_delete_leaves_no_empty_user_directory(us: FileUserSource, tmp_path: Path) -> None:
    user_dir = Path(us._get_manager("alice")._registry.get_source_properties("metadata")["connection"]["path"]).parent
    assert user_dir.is_dir()
    await us.delete_user("alice")
    assert not user_dir.exists()

