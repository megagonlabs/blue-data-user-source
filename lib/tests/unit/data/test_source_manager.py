from typing import Any

import pytest

from blue_data_user_source.interfaces import DataSource
from blue_data_user_source.data.registry import UserDataRegistry
from blue_data_user_source.types import QueryError
from tests.doubles.sources import InMemoryGraphSource, InMemoryVectorSource


class _NoOpSource(DataSource):
    async def query(self, query: str) -> list[Any]:
        return []


@pytest.fixture
def reg(graph_store: InMemoryGraphSource, vector_store: InMemoryVectorSource) -> UserDataRegistry:
    return UserDataRegistry(graph_store, vector_store)


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


async def test_add_node_stores_value_retrievable_via_query_nodes(
    reg: UserDataRegistry, graph_store: InMemoryGraphSource
) -> None:
    await reg.add_node("u1:entity:alice", ["ENTITY"], {"key": "alice", "database": "u1"})
    nodes = await reg.query_nodes(labels=["ENTITY"], properties={"database": "u1"})
    assert any(n["properties"].get("key") == "alice" for n in nodes)


async def test_add_edge_connects_nodes_traversable_via_query_neighbors(
    reg: UserDataRegistry,
) -> None:
    await reg.add_node("n1", ["ENTITY"], {"key": "alice"})
    await reg.add_node("n2", ["LITERAL"], {"value": "28"})
    await reg.add_edge("n1", "n2", "HAS_PROPERTY")
    neighbors = await reg.query_neighbors("n1", edge_type="HAS_PROPERTY")
    assert len(neighbors) == 1
    assert neighbors[0]["id"] == "n2"


async def test_set_vector_stores_value_retrievable_via_execute_vector(
    reg: UserDataRegistry, vector_store: InMemoryVectorSource
) -> None:
    await reg.set_vector("u1:vec:entry-1", "skills: Python", {"source_id": "src-1"})
    results = await reg.execute_vector("Python skills")
    assert len(results) == 1
    assert results[0]["text"] == "skills: Python"


async def test_dual_write_graph_and_vector_are_both_populated(
    reg: UserDataRegistry,
    graph_store: InMemoryGraphSource,
    vector_store: InMemoryVectorSource,
) -> None:
    await reg.add_node("u1:entity:alice", ["ENTITY"], {"key": "alice", "database": "u1"})
    await reg.set_vector("u1:vec:entry-1", "location: Remote", {})

    graph_nodes = await graph_store.query_nodes(labels=["ENTITY"])
    vector_results = await vector_store.query("remote work")

    assert any(n["properties"].get("key") == "alice" for n in graph_nodes)
    assert any(r.get("text") == "location: Remote" for r in vector_results)
