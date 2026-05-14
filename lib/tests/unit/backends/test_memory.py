import pytest

from blue_data_user_source.backends.memory import (
    MemoryJsonSource,
    MemoryVectorSource,
    memory_store_factory,
)


# ── MemoryJsonSource ──────────────────────────────────────────────────────────

async def test_json_set_and_get() -> None:
    store = MemoryJsonSource()
    await store.set("k1", {"a": 1})
    assert await store.get("k1") == {"a": 1}


async def test_json_get_missing_returns_none() -> None:
    assert await MemoryJsonSource().get("nope") is None


async def test_json_delete_removes_key() -> None:
    store = MemoryJsonSource()
    await store.set("k", {"v": 1})
    await store.delete("k")
    assert await store.get("k") is None


async def test_json_delete_missing_is_noop() -> None:
    await MemoryJsonSource().delete("not-there")


async def test_json_query_returns_all_values() -> None:
    store = MemoryJsonSource()
    await store.set("a", {"x": 1})
    await store.set("b", {"x": 2})
    results = await store.query("*")
    assert len(results) == 2


async def test_json_keys_returns_all_keys() -> None:
    store = MemoryJsonSource()
    await store.set("foo:1", {})
    await store.set("bar:1", {})
    keys = await store.keys()
    assert set(keys) == {"foo:1", "bar:1"}


async def test_json_keys_with_prefix_filters() -> None:
    store = MemoryJsonSource()
    await store.set("foo:1", {})
    await store.set("foo:2", {})
    await store.set("bar:1", {})
    keys = await store.keys(prefix="foo:")
    assert set(keys) == {"foo:1", "foo:2"}


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


# ── memory_store_factory ──────────────────────────────────────────────────────

def test_factory_returns_json_and_vector_source() -> None:
    json_src, vec_src = memory_store_factory("any-db")
    assert isinstance(json_src, MemoryJsonSource)
    assert isinstance(vec_src, MemoryVectorSource)


def test_factory_returns_independent_instances() -> None:
    a_json, a_vec = memory_store_factory("db-a")
    b_json, b_vec = memory_store_factory("db-b")
    assert a_json is not b_json
    assert a_vec is not b_vec
