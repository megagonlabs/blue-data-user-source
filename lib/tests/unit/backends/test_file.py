from pathlib import Path

import pytest

from blue_data_user_source.backends.file import (
    FileGraphSource,
    FileVectorSource,
    file_store_factory,
)


# ── FileGraphSource ───────────────────────────────────────────────────────────

async def test_graph_add_and_get_node(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.add_node("n1", ["ENTITY"], {"key": "alice", "database": "db"})
    node = await g.get_node("n1")
    assert node is not None
    assert node["id"] == "n1"
    assert "ENTITY" in node["labels"]
    assert node["properties"]["key"] == "alice"


async def test_graph_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "graph.json"
    await FileGraphSource(path).add_node("n1", ["ENTITY"], {"key": "alice"})
    node = await FileGraphSource(path).get_node("n1")
    assert node is not None
    assert node["properties"]["key"] == "alice"


async def test_graph_get_missing_node_returns_none(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    assert await g.get_node("nope") is None


async def test_graph_get_on_missing_file_returns_none(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "nonexistent.json")
    assert await g.get_node("x") is None


async def test_graph_add_node_upserts_existing(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.add_node("n1", ["ENTITY"], {"key": "alice"})
    await g.add_node("n1", ["ENTITY"], {"key": "alice_updated"})
    node = await g.get_node("n1")
    assert node is not None
    assert node["properties"]["key"] == "alice_updated"


async def test_graph_delete_node_removes_it(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.add_node("n1", ["ENTITY"], {})
    await g.delete_node("n1")
    assert await g.get_node("n1") is None


async def test_graph_delete_node_also_removes_incident_edges(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.add_node("n1", ["ENTITY"], {})
    await g.add_node("n2", ["LITERAL"], {})
    eid = await g.add_edge("n1", "n2", "HAS_PROPERTY")
    await g.delete_node("n1")
    data = g._read()
    assert eid not in data["edges"]


async def test_graph_delete_missing_node_is_noop(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.delete_node("not-there")


async def test_graph_add_edge_and_query_neighbors(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.add_node("n1", ["ENTITY"], {"key": "alice"})
    await g.add_node("n2", ["LITERAL"], {"value": "28"})
    await g.add_edge("n1", "n2", "HAS_PROPERTY")
    neighbors = await g.query_neighbors("n1", edge_type="HAS_PROPERTY", direction="out")
    assert len(neighbors) == 1
    assert neighbors[0]["id"] == "n2"


async def test_graph_delete_edge(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.add_node("n1", ["ENTITY"], {})
    await g.add_node("n2", ["LITERAL"], {})
    eid = await g.add_edge("n1", "n2", "HAS_PROPERTY")
    await g.delete_edge(eid)
    neighbors = await g.query_neighbors("n1")
    assert neighbors == []


async def test_graph_delete_missing_edge_is_noop(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.delete_edge("not-there")


async def test_graph_query_nodes_returns_all_when_no_filter(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.add_node("n1", ["ENTITY"], {})
    await g.add_node("n2", ["LITERAL"], {})
    nodes = await g.query_nodes()
    assert len(nodes) == 2


async def test_graph_query_nodes_filters_by_label(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.add_node("n1", ["ENTITY"], {})
    await g.add_node("n2", ["LITERAL"], {})
    nodes = await g.query_nodes(labels=["ENTITY"])
    assert len(nodes) == 1
    assert nodes[0]["id"] == "n1"


async def test_graph_query_nodes_filters_by_property(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.add_node("n1", ["ENTITY"], {"database": "db-a"})
    await g.add_node("n2", ["ENTITY"], {"database": "db-b"})
    nodes = await g.query_nodes(properties={"database": "db-a"})
    assert len(nodes) == 1
    assert nodes[0]["id"] == "n1"


async def test_graph_text_search(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.add_node("n1", ["LITERAL"], {"value": "Python programming"})
    await g.add_node("n2", ["LITERAL"], {"value": "SQL databases"})
    results = await g.query("python")
    assert len(results) == 1
    assert results[0]["id"] == "n1"


async def test_graph_cypher_raises_not_implemented(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    with pytest.raises(NotImplementedError):
        await g.cypher("MATCH (n) RETURN n")


async def test_graph_creates_parent_directories(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "nested" / "deep" / "graph.json")
    await g.add_node("n1", ["ENTITY"], {})
    assert await g.get_node("n1") is not None


async def test_graph_atomic_write_leaves_no_tmp_file(tmp_path: Path) -> None:
    g = FileGraphSource(tmp_path / "graph.json")
    await g.add_node("n1", ["ENTITY"], {})
    assert not (tmp_path / "graph.tmp").exists()


# ── FileVectorSource ──────────────────────────────────────────────────────────

async def test_vector_set_and_get(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "vectors.json")
    await store.set("k1", "hello world", {"tag": "test"})
    entry = await store.get("k1")
    assert entry is not None
    assert entry["text"] == "hello world"
    assert entry["metadata"] == {"tag": "test"}


async def test_vector_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "vectors.json"
    await FileVectorSource(path).set("k", "text", {"m": 1})
    entry = await FileVectorSource(path).get("k")
    assert entry is not None
    assert entry["text"] == "text"


async def test_vector_set_no_metadata_defaults_to_empty_dict(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "vectors.json")
    await store.set("k", "text")
    entry = await store.get("k")
    assert entry is not None
    assert entry["metadata"] == {}


async def test_vector_get_missing_returns_none(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "vectors.json")
    assert await store.get("nope") is None


async def test_vector_get_on_missing_file_returns_none(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "nonexistent.json")
    assert await store.get("x") is None


async def test_vector_delete_removes_entry(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "vectors.json")
    await store.set("k", "text")
    await store.delete("k")
    assert await store.get("k") is None


async def test_vector_delete_missing_is_noop(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "vectors.json")
    await store.delete("not-there")


async def test_vector_query_returns_up_to_top_k(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "vectors.json")
    for i in range(5):
        await store.set(f"k{i}", f"text {i}")
    assert len(await store.query("q", top_k=3)) == 3


async def test_vector_query_returns_all_when_fewer_than_top_k(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "vectors.json")
    await store.set("k", "text")
    assert len(await store.query("q", top_k=10)) == 1


async def test_vector_query_on_empty_store_returns_empty_list(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "vectors.json")
    assert await store.query("q") == []


async def test_vector_query_result_includes_score(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "vectors.json")
    await store.set("k1", "hello world")
    results = await store.query("hello", top_k=1)
    assert len(results) == 1
    assert "score" in results[0]
    assert isinstance(results[0]["score"], float)


async def test_vector_creates_parent_directories(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "nested" / "deep" / "vectors.json")
    await store.set("k", "text")
    assert await store.get("k") is not None


async def test_vector_atomic_write_leaves_no_tmp_file(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "vectors.json")
    await store.set("k", "text")
    assert not (tmp_path / "vectors.tmp").exists()


# ── file_store_factory ────────────────────────────────────────────────────────

def test_factory_returns_file_graph_and_vector_source(tmp_path: Path) -> None:
    factory = file_store_factory(tmp_path)
    graph_src, vec_src = factory("db-a")
    assert isinstance(graph_src, FileGraphSource)
    assert isinstance(vec_src, FileVectorSource)


def test_factory_creates_database_directory(tmp_path: Path) -> None:
    factory = file_store_factory(tmp_path)
    factory("my-db")
    assert (tmp_path / "my-db").is_dir()


def test_factory_returns_independent_instances_per_database(tmp_path: Path) -> None:
    factory = file_store_factory(tmp_path)
    a_graph, _ = factory("db-a")
    b_graph, _ = factory("db-b")
    assert a_graph is not b_graph


async def test_factory_stores_are_isolated_per_database(tmp_path: Path) -> None:
    factory = file_store_factory(tmp_path)
    a_graph, _ = factory("db-a")
    b_graph, _ = factory("db-b")
    await a_graph.add_node("n1", ["ENTITY"], {"key": "alice"})
    assert await b_graph.get_node("n1") is None


def test_factory_expands_tilde_in_base_dir(tmp_path: Path) -> None:
    import os
    os.environ["HOME"] = str(tmp_path)
    factory = file_store_factory("~/userdb")
    factory("db")
    assert (tmp_path / "userdb" / "db").is_dir()
