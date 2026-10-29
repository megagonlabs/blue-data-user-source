"""POST /{name}/query takes bounds on the query's LLM calls (#178)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from blue_data_user_api.app import app


@pytest.fixture
def source():
    fake = MagicMock()
    fake.async_execute_query = AsyncMock(return_value=([], "sess-1"))
    app.state.source = fake
    return fake


@pytest.fixture
def client(source):
    return TestClient(app)


def test_the_bounds_reach_the_library(client, source):
    body = {"query": "q", "max_subqueries": 0, "max_kb_turns": 6, "max_interaction_rounds": 1}
    assert client.post("/alice/query", json=body).status_code == 200
    props = source.async_execute_query.await_args.kwargs["optional_properties"]
    assert (props["max_subqueries"], props["max_kb_turns"], props["max_interaction_rounds"]) == (0, 6, 1)


def test_unset_bounds_leave_the_library_defaults(client, source):
    assert client.post("/alice/query", json={"query": "q"}).status_code == 200
    props = source.async_execute_query.await_args.kwargs["optional_properties"]
    assert not {"max_subqueries", "max_kb_turns", "max_interaction_rounds"} & set(props)


@pytest.mark.parametrize("bad", [{"max_subqueries": -1}, {"max_kb_turns": 0}, {"max_interaction_rounds": -1}])
def test_a_bad_bound_is_rejected(client, source, bad):
    assert client.post("/alice/query", json={"query": "q", **bad}).status_code == 422
    source.async_execute_query.assert_not_awaited()
