from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from blue_data_user_source.data.manager import StoreFactory
from blue_data_user_source.interfaces import DataSource
from blue_data_user_source.source import UserSource
from blue_data_user_source.types import QueryError, QueryResult


class _NoOpSource(DataSource):
    async def query(self, query: str) -> list[Any]:
        return []


class _FixedSource(DataSource):
    def __init__(self, results: list[Any]) -> None:
        self._results = results

    async def query(self, q: str) -> list[Any]:
        return self._results


@pytest.fixture
async def source(user_id: str, store_factory: StoreFactory) -> UserSource:
    us = UserSource(properties={"database": user_id, "store_factory": store_factory})
    await us.create_database(user_id)
    return us


def _mock_reasoner(
    questions: list[str],
    needs_interaction: bool = False,
    clarification_data: list[Any] | None = None,
) -> Any:
    instance = AsyncMock()
    instance.contextualize_query = AsyncMock(return_value="rewritten query")
    instance.expand_query = AsyncMock(return_value=questions)
    instance.assess_query_results = AsyncMock(return_value=[])
    instance.assess_user_verification = AsyncMock(return_value=needs_interaction)
    if clarification_data is not None:
        instance.request_user_clarification = AsyncMock(return_value=(clarification_data, {}))
    return instance


# ── constructor ──────────────────────────────────────────────────────────────

def test_init_stores_default_database(store_factory: StoreFactory) -> None:
    us = UserSource(properties={"database": "my-db", "store_factory": store_factory})
    assert us._default_database == "my-db"


def test_init_with_no_properties_has_no_default() -> None:
    us = UserSource()
    assert us._default_database is None


def test_init_with_empty_dict_has_no_default() -> None:
    us = UserSource(properties={})
    assert us._default_database is None


# ── _resolve_database ────────────────────────────────────────────────────────

def test_resolve_database_raises_when_no_db_configured() -> None:
    us = UserSource()
    with pytest.raises(QueryError, match="No database specified"):
        us._resolve_database(None)


def test_resolve_database_uses_explicit_argument() -> None:
    us = UserSource()
    assert us._resolve_database("explicit-db") == "explicit-db"


def test_resolve_database_falls_back_to_default(store_factory: StoreFactory) -> None:
    us = UserSource(properties={"database": "default-db", "store_factory": store_factory})
    assert us._resolve_database(None) == "default-db"


def test_resolve_database_explicit_overrides_default(store_factory: StoreFactory) -> None:
    us = UserSource(properties={"database": "default-db", "store_factory": store_factory})
    assert us._resolve_database("other-db") == "other-db"


# ── create_database / create_user ────────────────────────────────────────────

async def test_create_database_registers_user_in_manager(
    source: UserSource, user_id: str
) -> None:
    assert user_id in source._data_manager._registries


async def test_create_user_is_alias_for_create_database(
    store_factory: StoreFactory,
) -> None:
    us = UserSource(properties={"store_factory": store_factory})
    await us.create_user("alias-db")
    assert "alias-db" in us._data_manager._registries


async def test_create_database_raises_without_store_factory() -> None:
    us = UserSource()
    with pytest.raises(ValueError, match="store_factory"):
        await us.create_database("any-db")


# ── execute_query ────────────────────────────────────────────────────────────

async def test_execute_query_returns_one_result_per_expanded_question(
    source: UserSource, user_id: str
) -> None:
    mock = _mock_reasoner(["q1", "q2", "q3"])
    with patch("blue_data_user_source.source.UserQueryReasoner", return_value=mock):
        results = await source.execute_query("any query", database=user_id)
    assert len(results) == 3
    assert all(isinstance(r, QueryResult) for r in results)


async def test_execute_query_passes_question_as_result_query_field(
    source: UserSource, user_id: str
) -> None:
    mock = _mock_reasoner(["What skills?"])
    with patch("blue_data_user_source.source.UserQueryReasoner", return_value=mock):
        results = await source.execute_query("skills?", database=user_id)
    assert results[0].query == "What skills?"


async def test_execute_query_passes_session_id_to_reasoner(
    source: UserSource, user_id: str
) -> None:
    mock = _mock_reasoner(["q"])
    with patch("blue_data_user_source.source.UserQueryReasoner", return_value=mock) as MockClass:
        await source.execute_query(
            "q", database=user_id, optional_properties={"session": "sess-abc"}
        )
    MockClass.assert_called_once_with(source=source, database=user_id, session_id="sess-abc")


async def test_execute_query_no_session_passes_none(
    source: UserSource, user_id: str
) -> None:
    mock = _mock_reasoner(["q"])
    with patch("blue_data_user_source.source.UserQueryReasoner", return_value=mock) as MockClass:
        await source.execute_query("q", database=user_id)
    MockClass.assert_called_once_with(source=source, database=user_id, session_id=None)


async def test_execute_query_calls_clarification_when_metrics_fail(
    source: UserSource, user_id: str
) -> None:
    mock = _mock_reasoner(["q"], needs_interaction=True, clarification_data=["clarified"])
    with patch("blue_data_user_source.source.UserQueryReasoner", return_value=mock):
        results = await source.execute_query("q", database=user_id)
    mock.request_user_clarification.assert_awaited_once()
    assert results[0].results == ["clarified"]


async def test_execute_query_skips_clarification_when_metrics_pass(
    source: UserSource, user_id: str
) -> None:
    mock = _mock_reasoner(["q"], needs_interaction=False)
    with patch("blue_data_user_source.source.UserQueryReasoner", return_value=mock):
        await source.execute_query("q", database=user_id)
    mock.request_user_clarification.assert_not_awaited()


async def test_execute_query_raises_when_no_database_configured() -> None:
    us = UserSource()
    with pytest.raises(QueryError):
        await us.execute_query("anything")


# ── import_source ────────────────────────────────────────────────────────────

async def test_import_source_type1_registers_source_in_registry(
    source: UserSource, user_id: str
) -> None:
    await source.import_source(_NoOpSource(), database=user_id)
    reg = source._data_manager._registries[user_id]
    source_nodes = await reg.query_nodes(labels=["SOURCE"])
    assert any("source_id" in n["properties"] for n in source_nodes)


async def test_import_source_non_list_queries_treated_as_type1(
    source: UserSource, user_id: str
) -> None:
    await source.import_source(
        _NoOpSource(), database=user_id, optional_properties={"queries": "not-a-list"}
    )
    reg = source._data_manager._registries[user_id]
    source_nodes = await reg.query_nodes(labels=["SOURCE"])
    assert any("source_id" in n["properties"] for n in source_nodes)


async def test_import_source_raises_when_no_database_configured() -> None:
    us = UserSource()
    with pytest.raises(QueryError):
        await us.import_source(_NoOpSource())
