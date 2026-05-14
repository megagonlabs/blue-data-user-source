from pathlib import Path

import pytest

from blue_data_user_source.backends.file import (
    FileJsonSource,
    FileVectorSource,
    file_store_factory,
)


# ── FileJsonSource ────────────────────────────────────────────────────────────

async def test_json_set_and_get(tmp_path: Path) -> None:
    store = FileJsonSource(tmp_path / "data.json")
    await store.set("k1", {"a": 1})
    assert await store.get("k1") == {"a": 1}


async def test_json_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    await FileJsonSource(path).set("k", {"v": 42})
    assert await FileJsonSource(path).get("k") == {"v": 42}


async def test_json_get_missing_returns_none(tmp_path: Path) -> None:
    store = FileJsonSource(tmp_path / "data.json")
    assert await store.get("nope") is None


async def test_json_get_on_missing_file_returns_none(tmp_path: Path) -> None:
    store = FileJsonSource(tmp_path / "nonexistent.json")
    assert await store.get("x") is None


async def test_json_delete_removes_key(tmp_path: Path) -> None:
    store = FileJsonSource(tmp_path / "data.json")
    await store.set("k", {"v": 1})
    await store.delete("k")
    assert await store.get("k") is None


async def test_json_delete_missing_is_noop(tmp_path: Path) -> None:
    store = FileJsonSource(tmp_path / "data.json")
    await store.delete("not-there")


async def test_json_query_returns_all_values(tmp_path: Path) -> None:
    store = FileJsonSource(tmp_path / "data.json")
    await store.set("a", {"x": 1})
    await store.set("b", {"x": 2})
    results = await store.query("*")
    assert len(results) == 2


async def test_json_query_on_empty_store_returns_empty_list(tmp_path: Path) -> None:
    store = FileJsonSource(tmp_path / "data.json")
    assert await store.query("*") == []


async def test_json_keys_returns_all_keys(tmp_path: Path) -> None:
    store = FileJsonSource(tmp_path / "data.json")
    await store.set("foo:1", {})
    await store.set("bar:1", {})
    assert set(await store.keys()) == {"foo:1", "bar:1"}


async def test_json_keys_with_prefix_filters(tmp_path: Path) -> None:
    store = FileJsonSource(tmp_path / "data.json")
    await store.set("foo:1", {})
    await store.set("foo:2", {})
    await store.set("bar:1", {})
    assert set(await store.keys(prefix="foo:")) == {"foo:1", "foo:2"}


async def test_json_keys_on_empty_store_returns_empty_list(tmp_path: Path) -> None:
    store = FileJsonSource(tmp_path / "data.json")
    assert await store.keys() == []


async def test_json_creates_parent_directories(tmp_path: Path) -> None:
    store = FileJsonSource(tmp_path / "nested" / "deep" / "data.json")
    await store.set("k", {"v": 1})
    assert await store.get("k") == {"v": 1}


async def test_json_atomic_write_leaves_no_tmp_file(tmp_path: Path) -> None:
    store = FileJsonSource(tmp_path / "data.json")
    await store.set("k", {"v": 1})
    assert not (tmp_path / "data.tmp").exists()


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


async def test_vector_creates_parent_directories(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "nested" / "deep" / "vectors.json")
    await store.set("k", "text")
    assert await store.get("k") is not None


async def test_vector_atomic_write_leaves_no_tmp_file(tmp_path: Path) -> None:
    store = FileVectorSource(tmp_path / "vectors.json")
    await store.set("k", "text")
    assert not (tmp_path / "vectors.tmp").exists()


# ── file_store_factory ────────────────────────────────────────────────────────

def test_factory_returns_file_json_and_vector_source(tmp_path: Path) -> None:
    factory = file_store_factory(tmp_path)
    json_src, vec_src = factory("db-a")
    assert isinstance(json_src, FileJsonSource)
    assert isinstance(vec_src, FileVectorSource)


def test_factory_creates_database_directory(tmp_path: Path) -> None:
    factory = file_store_factory(tmp_path)
    factory("my-db")
    assert (tmp_path / "my-db").is_dir()


def test_factory_returns_independent_instances_per_database(tmp_path: Path) -> None:
    factory = file_store_factory(tmp_path)
    a_json, _ = factory("db-a")
    b_json, _ = factory("db-b")
    assert a_json is not b_json


async def test_factory_stores_are_isolated_per_database(tmp_path: Path) -> None:
    factory = file_store_factory(tmp_path)
    a_json, _ = factory("db-a")
    b_json, _ = factory("db-b")
    await a_json.set("k", {"v": "a"})
    assert await b_json.get("k") is None


def test_factory_expands_tilde_in_base_dir(tmp_path: Path) -> None:
    import os
    os.environ["HOME"] = str(tmp_path)
    factory = file_store_factory("~/userdb")
    factory("db")
    assert (tmp_path / "userdb" / "db").is_dir()
