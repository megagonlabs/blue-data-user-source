"""A query's LLM calls are bounded, and a cheaper model reaches every part of it (#178).

Each sub-question is answered by the KB's agent, which makes most of a query's
calls: ``max_subqueries`` caps the sub-questions, ``max_kb_turns`` the agent's
turns for each, and ``model`` now runs the agent too (it was always gpt-4o).
Without one, the agent gets the reasoner's model, resolved by the same rule
(#190). The LLM and the KB's agent are stubbed: these tests count what would
be sent.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from blue_data_user_source import MemoryUserSource, QueryError
from blue_data_user_source.data.manager import UserDataManager

_SUBQUESTIONS = [f"What is Alice's facet {i}?" for i in range(5)]


@pytest.fixture(autouse=True)
def _default_models(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BLUE_DATA_LLM_PROVIDER", "BLUE_DATA_LLM_MODEL", "BLUE_DATA_USER_SOURCE_LLM_MODEL",
                 "BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL",
                 "BLUE_DATA_USER_SOURCE_EXTRACTION_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)


async def _fake_llm(prompt: str, *args: Any, properties: dict | None = None, **kwargs: Any) -> Any:
    if (properties or {}).get("response_format") == "json_object":
        # Expansion proposes five sub-questions; every metric passes; synthesis returns rows.
        return {"questions": _SUBQUESTIONS, "score": 1.0, "reasoning": "stub", "rows": []}
    return "What does Alice like?"


@pytest.fixture
async def source() -> MemoryUserSource:
    us = MemoryUserSource("budget", {"console": False})
    await us.create_user(
        "alice", registry_props={"backend": "memory"}, kb_source_props={"backend": "memory"},
        metadata_source_props={"backend": "memory"}, contact_source_props={"backend": "memory"},
        session_source_props={"backend": "memory"},
        doc_source_props={"embedding_model": "dummy", "search_mode": "bm25"}, onboard=False,
    )
    return us


@pytest.fixture
def kb_answer():
    """The KB agent's ``answer``, as the manager calls it for each sub-question."""
    answer = AsyncMock(return_value=([], {}))
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", _fake_llm), \
         patch.object(UserDataManager, "_ensure_kb_source") as kb:
        kb.return_value.answer = answer
        yield answer


async def _ask(source: MemoryUserSource, **props: Any) -> None:
    await source._run_query("what do I like?", database="alice", optional_properties=props)


def _questions(kb_answer: AsyncMock) -> list[str]:
    return [c.args[1] for c in kb_answer.await_args_list]


async def test_by_default_every_proposed_subquestion_is_answered(source, kb_answer) -> None:
    await _ask(source)
    assert len(_questions(kb_answer)) == len(_SUBQUESTIONS) + 1  # plus the rewritten query
    assert all("max_turns" not in c.kwargs for c in kb_answer.await_args_list)  # the KB's default
    # The reasoner's model, not the KB's own configuration (#190).
    assert {c.kwargs["model"] for c in kb_answer.await_args_list} == {"gpt-4o"}


async def test_the_configured_reasoning_model_reaches_the_kb_agent(
    source, kb_answer, monkeypatch,
) -> None:
    monkeypatch.setenv("BLUE_DATA_LLM_PROVIDER", "anthropic")
    await _ask(source)
    assert {c.kwargs["model"] for c in kb_answer.await_args_list} == {"claude-opus-4-8"}
    monkeypatch.setenv("BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL", "claude-haiku-4-8")
    kb_answer.reset_mock()
    await _ask(source)
    assert {c.kwargs["model"] for c in kb_answer.await_args_list} == {"claude-haiku-4-8"}


@pytest.mark.parametrize("cap", [0, 2])
async def test_max_subqueries_caps_the_subquestions(source, kb_answer, cap: int) -> None:
    await _ask(source, max_subqueries=cap)
    assert _questions(kb_answer) == [*_SUBQUESTIONS[:cap], "What does Alice like?"]


async def test_max_kb_turns_and_the_model_reach_the_kb_agent(source, kb_answer) -> None:
    await _ask(source, max_kb_turns=4, model="gpt-4o-mini")
    for call in kb_answer.await_args_list:
        assert call.kwargs["max_turns"] == 4
        assert call.kwargs["model"] == "gpt-4o-mini"


@pytest.mark.parametrize("props, message", [
    ({"max_subqueries": -1}, "max_subqueries must be an integer of at least 0"),
    ({"max_subqueries": True}, "max_subqueries must be an integer of at least 0"),
    ({"max_kb_turns": 0}, "max_kb_turns must be a positive integer"),
    ({"max_kb_turns": "5"}, "max_kb_turns must be a positive integer"),
    ({"max_interaction_rounds": -2}, "max_interaction_rounds must be an integer of at least 0"),
])
async def test_a_bad_bound_is_rejected_before_anything_runs(source, kb_answer, props, message) -> None:
    with pytest.raises(QueryError, match=message):
        await _ask(source, **props)
    kb_answer.assert_not_awaited()
    assert await source.list_sessions("alice") == {}


async def test_the_extraction_runs_on_the_model_given(source) -> None:
    """add_source's extraction always ran on the KB's default, gpt-4o (#178)."""
    import_text = AsyncMock()
    manager = source._get_manager("alice")
    kb = manager._ensure_kb_source()
    with patch.object(kb, "import_text", import_text):
        await source.add_text_source("Alice likes tea.", database="alice",
                                     optional_properties={"queries": ["q"], "model": "gpt-4o-mini"})
        assert import_text.await_args.kwargs["model"] == "gpt-4o-mini"
        await source.add_text_source("Alice likes jazz.", database="alice",
                                     optional_properties={"queries": ["q"]})
        assert import_text.await_args.kwargs["model"] == "gpt-4o"  # the provider's default (#190)


# ── zero bounds spend nothing, and an op is no query (#207) ───────────────────

async def test_no_subqueries_makes_no_expansion_call(source, kb_answer) -> None:
    with patch("blue_data_user_source.reasoning.reasoner.UserQueryReasoner.expand_query", AsyncMock()) as expand:
        await _ask(source, max_subqueries=0)
    expand.assert_not_awaited()
    assert kb_answer.await_count == 1


async def test_no_interaction_rounds_makes_no_assessment_calls(source, kb_answer) -> None:
    with patch("blue_data_user_source.reasoning.reasoner.UserQueryReasoner.assess_query_results",
               AsyncMock()) as assess:
        await _ask(source, max_interaction_rounds=0)
    assess.assert_not_awaited()


@pytest.mark.parametrize("query", [{"op": "SOMETHING"}, ["a"], None, 5])
async def test_a_query_that_is_no_string_is_refused_before_anything_runs(source, kb_answer, query) -> None:
    with pytest.raises(QueryError, match="must be a string"):
        await source.async_execute_query(query, database="alice")
    kb_answer.assert_not_awaited()
    assert await source.list_sessions("alice") == {}

