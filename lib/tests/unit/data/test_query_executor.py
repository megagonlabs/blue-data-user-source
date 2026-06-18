from typing import Any

import pytest

from blue_data_user_source.interfaces import DataSource
from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.types import ImportError


class _FixedResultSource(DataSource):
    """DataSource stub that returns a fixed list for any query."""

    def __init__(self, results: list[Any]) -> None:
        self._results = results

    async def query(self, query: str) -> list[Any]:
        return self._results


async def test_create_user_registers_graph_and_vector_stores(
    data_manager: UserDataManager, user_id: str
) -> None:
    reg = data_manager._registries[user_id]
    graph_src = await reg.get_source(f"{user_id}:graph")
    vector_src = await reg.get_source(f"{user_id}:vector")
    assert graph_src is not None
    assert vector_src is not None


async def test_execute_query_returns_aggregated_results(
    data_manager: UserDataManager, user_id: str
) -> None:
    reg = data_manager._registries[user_id]
    await reg.add_node(
        f"{user_id}:entity:alice",
        ["ENTITY"],
        {"key": "alice", "database": user_id, "schema_path": "alice"},
    )

    results, metadata = await data_manager.execute_query("what skills?", user_id)
    assert isinstance(results, list)
    assert "provenance" in metadata


async def test_execute_query_metadata_contains_provenance_entries(
    data_manager: UserDataManager, user_id: str
) -> None:
    _, metadata = await data_manager.execute_query("any query", user_id)
    assert len(metadata["provenance"]) >= 1
    for entry in metadata["provenance"]:
        assert "source" in entry
        assert "timestamp" in entry
        assert "confidence" in entry


async def test_import_source_type1_registers_source_in_registry(
    data_manager: UserDataManager, user_id: str
) -> None:
    source = _FixedResultSource(["resume text"])
    await data_manager.import_source(source, user_id, queries=None)

    reg = data_manager._registries[user_id]
    source_nodes = await reg.query_nodes(labels=["SOURCE"])
    assert len(source_nodes) == 1
    assert "source_id" in source_nodes[0]["properties"]


async def test_import_source_type2_raises_import_error_when_source_query_fails(
    data_manager: UserDataManager, user_id: str
) -> None:
    class _ErrorSource(_FixedResultSource):
        async def query(self, q: str) -> list[Any]:
            raise RuntimeError("disk read failed")

    from blue_data_user_source.types import ImportError as UserImportError

    with pytest.raises(UserImportError, match="Query over source failed"):
        await data_manager.import_source(_ErrorSource([]), user_id, queries=["q"])
