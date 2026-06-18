import pytest

from blue_data_user_source.backends.memory import (
    MemoryGraphSource,
    MemoryVectorSource,
    memory_store_factory,
)
from blue_data_user_source.interfaces import VectorSource


# ── MemoryGraphSource ─────────────────────────────────────────────────────────

async def test_graph_add_and_get_node() -> None:
    g = MemoryGraphSource()
    await g.add_node("n1", ["ENTITY"], {"key": "alice", "database": "db"})
    node = await g.get_node("n1")
    assert node is not None
    assert node["id"] == "n1"
    assert "ENTITY" in node["labels"]
    assert node["properties"]["key"] == "alice"


async def test_graph_get_missing_node_returns_none() -> None:
    g = MemoryGraphSource()
    assert await g.get_node("nope") is None


async def test_graph_add_node_upserts_existing() -> None:
    g = MemoryGraphSource()
    await g.add_node("n1", ["ENTITY"], {"key": "alice"})
    await g.add_node("n1", ["ENTITY"], {"key": "alice_updated"})
    node = await g.get_node("n1")
    assert node is not None
    assert node["properties"]["key"] == "alice_updated"


async def test_graph_delete_node_removes_it() -> None:
    g = MemoryGraphSource()
    await g.add_node("n1", ["ENTITY"], {})
    await g.delete_node("n1")
    assert await g.get_node("n1") is None


async def test_graph_delete_node_also_removes_incident_edges() -> None:
    g = MemoryGraphSource()
    await g.add_node("n1", ["ENTITY"], {})
    await g.add_node("n2", ["LITERAL"], {})
    eid = await g.add_edge("n1", "n2", "HAS_PROPERTY")
    await g.delete_node("n1")
    assert g._edges.get(eid) is None


async def test_graph_delete_missing_node_is_noop() -> None:
    g = MemoryGraphSource()
    await g.delete_node("not-there")  # should not raise


async def test_graph_add_edge_and_query_neighbors() -> None:
    g = MemoryGraphSource()
    await g.add_node("n1", ["ENTITY"], {"key": "alice"})
    await g.add_node("n2", ["LITERAL"], {"value": "28"})
    await g.add_edge("n1", "n2", "HAS_PROPERTY")
    neighbors = await g.query_neighbors("n1", edge_type="HAS_PROPERTY", direction="out")
    assert len(neighbors) == 1
    assert neighbors[0]["id"] == "n2"


async def test_graph_query_neighbors_direction_in() -> None:
    g = MemoryGraphSource()
    await g.add_node("fact", ["FACT"], {})
    await g.add_node("alice", ["ENTITY"], {"key": "alice"})
    await g.add_edge("fact", "alice", "HEAD")
    neighbors = await g.query_neighbors("alice", edge_type="HEAD", direction="in")
    assert len(neighbors) == 1
    assert neighbors[0]["id"] == "fact"


async def test_graph_query_neighbors_direction_both() -> None:
    g = MemoryGraphSource()
    await g.add_node("n1", ["ENTITY"], {})
    await g.add_node("n2", ["ENTITY"], {})
    await g.add_node("n3", ["ENTITY"], {})
    await g.add_edge("n1", "n2", "RELATED")
    await g.add_edge("n3", "n1", "RELATED")
    neighbors = await g.query_neighbors("n1", edge_type="RELATED", direction="both")
    ids = {n["id"] for n in neighbors}
    assert ids == {"n2", "n3"}


async def test_graph_delete_edge() -> None:
    g = MemoryGraphSource()
    await g.add_node("n1", ["ENTITY"], {})
    await g.add_node("n2", ["LITERAL"], {})
    eid = await g.add_edge("n1", "n2", "HAS_PROPERTY")
    await g.delete_edge(eid)
    neighbors = await g.query_neighbors("n1")
    assert neighbors == []


async def test_graph_delete_missing_edge_is_noop() -> None:
    g = MemoryGraphSource()
    await g.delete_edge("not-there")


async def test_graph_query_nodes_returns_all_when_no_filter() -> None:
    g = MemoryGraphSource()
    await g.add_node("n1", ["ENTITY"], {"database": "db"})
    await g.add_node("n2", ["LITERAL"], {"database": "db"})
    nodes = await g.query_nodes()
    assert len(nodes) == 2


async def test_graph_query_nodes_filters_by_label() -> None:
    g = MemoryGraphSource()
    await g.add_node("n1", ["ENTITY"], {})
    await g.add_node("n2", ["LITERAL"], {})
    nodes = await g.query_nodes(labels=["ENTITY"])
    assert len(nodes) == 1
    assert nodes[0]["id"] == "n1"


async def test_graph_query_nodes_filters_by_multiple_labels() -> None:
    g = MemoryGraphSource()
    await g.add_node("n1", ["ENTITY"], {})
    await g.add_node("n2", ["LITERAL"], {})
    await g.add_node("n3", ["SOURCE"], {})
    nodes = await g.query_nodes(labels=["ENTITY", "LITERAL"])
    ids = {n["id"] for n in nodes}
    assert ids == {"n1", "n2"}


async def test_graph_query_nodes_filters_by_property() -> None:
    g = MemoryGraphSource()
    await g.add_node("n1", ["ENTITY"], {"database": "db-a"})
    await g.add_node("n2", ["ENTITY"], {"database": "db-b"})
    nodes = await g.query_nodes(properties={"database": "db-a"})
    assert len(nodes) == 1
    assert nodes[0]["id"] == "n1"


async def test_graph_query_text_search() -> None:
    g = MemoryGraphSource()
    await g.add_node("n1", ["LITERAL"], {"value": "Python programming"})
    await g.add_node("n2", ["LITERAL"], {"value": "SQL databases"})
    results = await g.query("python")
    assert len(results) == 1
    assert results[0]["id"] == "n1"


async def test_graph_cypher_raises_not_implemented() -> None:
    g = MemoryGraphSource()
    with pytest.raises(NotImplementedError):
        await g.cypher("MATCH (n) RETURN n")


# ── MemoryVectorSource ────────────────────────────────────────────────────────

async def test_vector_set_and_get() -> None:
    store = MemoryVectorSource()
    await store.set("k1", "hello world", {"tag": "test"})
    entry = await store.get("k1")
    assert entry is not None
    assert entry["text"] == "hello world"
    assert entry["metadata"] == {"tag": "test"}


async def test_vector_set_no_metadata_defaults_to_empty_dict() -> None:
    store = MemoryVectorSource()
    await store.set("k", "text")
    entry = await store.get("k")
    assert entry is not None
    assert entry["metadata"] == {}


async def test_vector_get_missing_returns_none() -> None:
    assert await MemoryVectorSource().get("nope") is None


async def test_vector_delete_removes_entry() -> None:
    store = MemoryVectorSource()
    await store.set("k", "text")
    await store.delete("k")
    assert await store.get("k") is None


async def test_vector_delete_missing_is_noop() -> None:
    await MemoryVectorSource().delete("not-there")


async def test_vector_query_returns_up_to_top_k() -> None:
    store = MemoryVectorSource()
    for i in range(5):
        await store.set(f"k{i}", f"text {i}")
    results = await store.query("anything", top_k=3)
    assert len(results) == 3


async def test_vector_query_returns_all_when_fewer_than_top_k() -> None:
    store = MemoryVectorSource()
    await store.set("k1", "one")
    results = await store.query("q", top_k=10)
    assert len(results) == 1


async def test_vector_query_result_includes_score() -> None:
    store = MemoryVectorSource()
    await store.set("k1", "hello world")
    results = await store.query("hello", top_k=1)
    assert len(results) == 1
    assert "score" in results[0]
    assert isinstance(results[0]["score"], float)


# ── VectorSource._apply_threshold ─────────────────────────────────────────────

def _result(score: float, text: str = "x") -> dict:
    return {"score": score, "text": text, "metadata": {}}


def test_threshold_cuts_when_cumulative_drop_exceeds_threshold() -> None:
    results = [_result(0.95), _result(0.87), _result(0.40), _result(0.38)]
    assert len(VectorSource._apply_threshold(results, 10.0)) == 2


def test_threshold_does_not_cut_when_cumulative_drop_stays_below_threshold() -> None:
    results = [_result(1.00), _result(0.96), _result(0.93), _result(0.91)]
    assert len(VectorSource._apply_threshold(results, 10.0)) == 4


def test_threshold_accumulates_across_small_steps() -> None:
    results = [_result(1.00), _result(0.94), _result(0.884), _result(0.83)]
    assert len(VectorSource._apply_threshold(results, 10.0)) == 2


def test_threshold_zero_cuts_after_first_result() -> None:
    results = [_result(0.9), _result(0.8), _result(0.7)]
    assert len(VectorSource._apply_threshold(results, 0.0)) == 1


def test_threshold_single_result_is_returned_unchanged() -> None:
    results = [_result(0.75)]
    assert VectorSource._apply_threshold(results, 10.0) == results


def test_threshold_zero_score_pivot_contributes_zero_to_cumulative() -> None:
    results = [_result(0.9), _result(0.0), _result(0.0)]
    assert len(VectorSource._apply_threshold(results, 10.0)) == 1


async def test_vector_query_threshold_reduces_results() -> None:
    emb_map = {"a": [1.0, 0.0], "b": [0.0, 1.0], "q": [1.0, 0.0]}

    async def _fake_embed(text: str) -> list[float]:
        return emb_map[text]

    store = MemoryVectorSource()
    store._embed = _fake_embed  # type: ignore[method-assign]
    await store.set("a", "a")
    await store.set("b", "b")

    all_results = await store.query("q", top_k=10, threshold=None)
    assert len(all_results) == 2

    cut_results = await store.query("q", top_k=10, threshold=0.10)
    assert len(cut_results) == 1
    assert cut_results[0]["text"] == "a"


# ── memory_store_factory ──────────────────────────────────────────────────────

def test_factory_returns_graph_and_vector_source() -> None:
    graph_src, vec_src = memory_store_factory("any-db")
    assert isinstance(graph_src, MemoryGraphSource)
    assert isinstance(vec_src, MemoryVectorSource)


def test_factory_returns_independent_instances() -> None:
    a_graph, a_vec = memory_store_factory("db-a")
    b_graph, b_vec = memory_store_factory("db-b")
    assert a_graph is not b_graph
    assert a_vec is not b_vec
