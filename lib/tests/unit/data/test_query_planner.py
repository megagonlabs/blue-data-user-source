import pytest

from blue_data_user_source.data.planner import UserDataPlanner
from blue_data_user_source.data.registry import UserDataRegistry
from tests.doubles.sources import InMemoryGraphSource, InMemoryVectorSource


@pytest.fixture
async def planner(
    graph_store: InMemoryGraphSource, vector_store: InMemoryVectorSource
) -> UserDataPlanner:
    reg = UserDataRegistry(graph_store, vector_store)
    await reg.register_source("u1:graph", graph_store)
    await reg.register_source("u1:vector", vector_store)
    return UserDataPlanner(reg)


async def test_plan_produces_two_steps_for_both_generic_stores(
    planner: UserDataPlanner,
) -> None:
    plan = await planner.plan("jobs suitable for me", "u1")
    assert len(plan) == 2
    source_ids = {step.source_id for step in plan}
    assert "u1:graph" in source_ids
    assert "u1:vector" in source_ids


async def test_plan_subqueries_match_original_query(planner: UserDataPlanner) -> None:
    query = "what skills do I have?"
    plan = await planner.plan(query, "u1")
    for step in plan:
        assert step.subquery == query
