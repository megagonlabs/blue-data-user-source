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


async def test_create_user_registers_json_and_vector_stores(
    data_manager: UserDataManager, user_id: str
) -> None:
    reg = data_manager._registries[user_id]
    json_src = await reg.get_source(f"{user_id}:json")
    vector_src = await reg.get_source(f"{user_id}:vector")
    assert json_src is not None
    assert vector_src is not None


async def test_execute_query_returns_aggregated_results(
    data_manager: UserDataManager, user_id: str
) -> None:
    reg = data_manager._registries[user_id]
    await reg.set_json(f"{user_id}:data:e1", {"key": "skills", "value": ["Python"]})

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
    json_values = await reg.execute_json("$")
    source_entries = [v for v in json_values if "source_id" in v]
    assert len(source_entries) == 1


async def test_import_source_type2_writes_to_both_stores(
    data_manager: UserDataManager, user_id: str
) -> None:
    source = _FixedResultSource(["Python", "SQL"])
    await data_manager.import_source(source, user_id, queries=["What skills?"])

    reg = data_manager._registries[user_id]

    json_values = await reg.execute_json("$")
    data_entries = [v for v in json_values if v.get("key") == "What skills?"]
    assert len(data_entries) == 1

    vector_entries = await reg.execute_vector("skills")
    assert len(vector_entries) >= 1


async def test_import_source_type2_dual_write_both_stores_populated(
    data_manager: UserDataManager, user_id: str
) -> None:
    source = _FixedResultSource(["remote"])
    await data_manager.import_source(source, user_id, queries=["location preference?"])

    reg = data_manager._registries[user_id]
    json_entries = await reg.execute_json("$")
    vector_entries = await reg.execute_vector("location")

    assert any(e.get("key") == "location preference?" for e in json_entries)
    assert len(vector_entries) >= 1


async def test_import_source_type2_raises_import_error_when_source_query_fails(
    data_manager: UserDataManager, user_id: str
) -> None:
    class _ErrorSource(_FixedResultSource):
        async def query(self, q: str) -> list[Any]:
            raise RuntimeError("disk read failed")

    from blue_data_user_source.types import ImportError as UserImportError

    with pytest.raises(UserImportError, match="Query over source failed"):
        await data_manager.import_source(_ErrorSource([]), user_id, queries=["q"])
