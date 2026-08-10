"""Tests for UserDataPlanner."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from blue_data_user_source.data.planner import SubqueryPlan, UserDataPlanner


@pytest.fixture
def planner() -> UserDataPlanner:
    registry = MagicMock()
    registry.list_sources.return_value = ["kb", "metadata"]
    return UserDataPlanner(registry)


async def test_plan_produces_one_step_per_source(planner: UserDataPlanner) -> None:
    plan = await planner.plan("what are my skills?")
    assert len(plan) == 2


async def test_plan_step_source_ids_match_registry(planner: UserDataPlanner) -> None:
    plan = await planner.plan("q")
    assert {step.source_id for step in plan} == {"kb", "metadata"}


async def test_plan_subquery_matches_original_query(planner: UserDataPlanner) -> None:
    plan = await planner.plan("what skills do I have?")
    assert all(step.subquery == "what skills do I have?" for step in plan)


async def test_plan_returns_empty_when_no_sources() -> None:
    registry = MagicMock()
    registry.list_sources.return_value = []
    plan = await UserDataPlanner(registry).plan("q")
    assert plan == []


async def test_plan_step_is_subquery_plan_instance(planner: UserDataPlanner) -> None:
    plan = await planner.plan("q")
    assert all(isinstance(step, SubqueryPlan) for step in plan)


async def test_plan_single_source() -> None:
    registry = MagicMock()
    registry.list_sources.return_value = ["kb"]
    plan = await UserDataPlanner(registry).plan("skills?")
    assert len(plan) == 1
    assert plan[0].source_id == "kb"
    assert plan[0].subquery == "skills?"
