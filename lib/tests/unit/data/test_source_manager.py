from typing import Any

import pytest

from blue_data_user_source.interfaces import DataSource
from blue_data_user_source.data.registry import UserDataRegistry
from blue_data_user_source.types import QueryError
from tests.doubles.sources import InMemoryJsonSource, InMemoryVectorSource


class _NoOpSource(DataSource):
    async def query(self, query: str) -> list[Any]:
        return []


@pytest.fixture
def reg(json_store: InMemoryJsonSource, vector_store: InMemoryVectorSource) -> UserDataRegistry:
    return UserDataRegistry(json_store, vector_store)


async def test_register_source_can_be_retrieved(reg: UserDataRegistry) -> None:
    source = _NoOpSource()
    await reg.register_source("src-1", source)
    result = await reg.get_source("src-1")
    assert result is source


async def test_get_nonexistent_source_returns_none(reg: UserDataRegistry) -> None:
    result = await reg.get_source("does-not-exist")
    assert result is None


async def test_execute_unknown_source_raises_query_error(reg: UserDataRegistry) -> None:
    with pytest.raises(QueryError, match="Source not found"):
        await reg.execute("what skills?", "missing-source")


async def test_set_json_stores_value_retrievable_via_execute_json(
    reg: UserDataRegistry, json_store: InMemoryJsonSource
) -> None:
    await reg.set_json("u1:data:entry-1", {"key": "skills", "value": ["Python"]})
    results = await reg.execute_json("$.u1.data[*]")
    assert any(r.get("key") == "skills" for r in results)


async def test_set_vector_stores_value_retrievable_via_execute_vector(
    reg: UserDataRegistry, vector_store: InMemoryVectorSource
) -> None:
    await reg.set_vector("u1:data:entry-1", "skills: Python", {"source_id": "src-1"})
    results = await reg.execute_vector("Python skills")
    assert len(results) == 1
    assert results[0]["text"] == "skills: Python"


async def test_dual_write_json_and_vector_are_both_populated(
    reg: UserDataRegistry,
    json_store: InMemoryJsonSource,
    vector_store: InMemoryVectorSource,
) -> None:
    key = "u1:data:entry-99"
    await reg.set_json(key, {"key": "location", "value": ["Remote"]})
    await reg.set_vector(key, "location: Remote", {})

    json_results = await json_store.query("*")
    vector_results = await vector_store.query("remote work")

    assert any(r.get("key") == "location" for r in json_results)
    assert any(r.get("text") == "location: Remote" for r in vector_results)
