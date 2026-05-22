import pytest

from blue_data_user_source.backends.memory import (
    MemoryJsonSource,
    MemoryVectorSource,
    memory_store_factory,
)
from blue_data_user_source.interfaces import VectorSource


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
    # Threshold is in % units (10.0 = 10% cumulative).
    # step 0→1: (0.95-0.87)/0.95*100 = 8.4%  → c_p=8.4  < 10 → no cut
    # step 1→2: (0.87-0.40)/0.87*100 = 54.0% → c_p=62.4 > 10 → cut after idx 1
    results = [_result(0.95), _result(0.87), _result(0.40), _result(0.38)]
    assert len(VectorSource._apply_threshold(results, 10.0)) == 2


def test_threshold_does_not_cut_when_cumulative_drop_stays_below_threshold() -> None:
    # step 0→1: 4.0%  → c_p=4.0
    # step 1→2: 3.1%  → c_p=7.1
    # step 2→3: 2.2%  → c_p=9.3  < 10 → no cut anywhere
    results = [_result(1.00), _result(0.96), _result(0.93), _result(0.91)]
    assert len(VectorSource._apply_threshold(results, 10.0)) == 4


def test_threshold_accumulates_across_small_steps() -> None:
    # Each step drops ~6%; cumulative exceeds 10% after 2 steps.
    # step 0→1: 6.0%  → c_p=6.0  < 10 → no cut
    # step 1→2: 5.96% → c_p=11.96 > 10 → cut after idx 1
    results = [_result(1.00), _result(0.94), _result(0.884), _result(0.83)]
    assert len(VectorSource._apply_threshold(results, 10.0)) == 2


def test_threshold_zero_cuts_after_first_result() -> None:
    # threshold=0.0: any positive cumulative % (>0) triggers immediately
    results = [_result(0.9), _result(0.8), _result(0.7)]
    assert len(VectorSource._apply_threshold(results, 0.0)) == 1


def test_threshold_single_result_is_returned_unchanged() -> None:
    results = [_result(0.75)]
    assert VectorSource._apply_threshold(results, 10.0) == results


def test_threshold_zero_score_pivot_contributes_zero_to_cumulative() -> None:
    # When s_i == 0, the guard returns p=0 (no contribution).
    # step 0→1: (0.9-0.0)/0.9*100 = 100% → c_p=100 > 10 → cut after idx 0
    results = [_result(0.9), _result(0.0), _result(0.0)]
    assert len(VectorSource._apply_threshold(results, 10.0)) == 1


async def test_vector_query_threshold_reduces_results() -> None:
    # Patch _embed on the instance so embeddings are fully controlled.
    # "a" and the query both map to [1,0]; "b" maps to [0,1].
    # cosine("a", query)=1.0, cosine("b", query)=0.0 → 100% drop → threshold cuts after "a".
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

def test_factory_returns_json_and_vector_source() -> None:
    json_src, vec_src = memory_store_factory("any-db")
    assert isinstance(json_src, MemoryJsonSource)
    assert isinstance(vec_src, MemoryVectorSource)


def test_factory_returns_independent_instances() -> None:
    a_json, a_vec = memory_store_factory("db-a")
    b_json, b_vec = memory_store_factory("db-b")
    assert a_json is not b_json
    assert a_vec is not b_vec
