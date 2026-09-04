"""Tests for UserQueryReasoner."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.reasoning.metric import MetricEvaluation
from blue_data_user_source.reasoning.reasoner import UserQueryReasoner


@pytest.fixture
def reasoner(manager: UserDataManager) -> UserQueryReasoner:
    return UserQueryReasoner(source=MagicMock(), manager=manager)


# ── contextualize_query ───────────────────────────────────────────────────────

async def test_contextualize_query_returns_llm_response(reasoner: UserQueryReasoner) -> None:
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value="rewritten query")):
        result = await reasoner.contextualize_query("jobs suitable for me")
    assert result == "rewritten query"


async def test_contextualize_query_falls_back_to_original_on_empty(reasoner: UserQueryReasoner) -> None:
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value="")):
        result = await reasoner.contextualize_query("my query")
    assert result == "my query"


# ── expand_query ──────────────────────────────────────────────────────────────

async def test_expand_query_returns_questions_from_json(reasoner: UserQueryReasoner) -> None:
    questions = ["What skills does the user have?", "Does the user prefer remote?"]
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value={"questions": questions})):
        result = await reasoner.expand_query("jobs suitable for me")
    assert result == questions


async def test_expand_query_returns_empty_when_no_expansion_needed(reasoner: UserQueryReasoner) -> None:
    """A narrow, already-specific query legitimately expands to no sub-questions."""
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value={"questions": []})):
        result = await reasoner.expand_query("my query")
    assert result == []


async def test_expand_query_returns_empty_on_non_dict_response(reasoner: UserQueryReasoner) -> None:
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value="not a dict")):
        result = await reasoner.expand_query("my query")
    assert result == []


async def test_expand_query_caps_at_five(reasoner: UserQueryReasoner) -> None:
    questions = [f"question {i}" for i in range(8)]
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value={"questions": questions})):
        result = await reasoner.expand_query("my query")
    assert result == questions[:5]


async def test_expand_query_includes_schema_facets_in_prompt(reasoner: UserQueryReasoner) -> None:
    captured: dict = {}

    async def fake_llm_complete(prompt: str, **kwargs):
        captured["prompt"] = prompt
        return {"questions": []}

    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", fake_llm_complete):
        await reasoner.expand_query("what are my skills?")

    assert "HAS_SKILL" in captured["prompt"]


# ── assess_user_interaction ───────────────────────────────────────────────────

async def test_assess_user_interaction_false_when_all_pass(reasoner: UserQueryReasoner) -> None:
    passing = [
        MetricEvaluation(name="completeness", score=0.9, reasoning="enough", passes=True),
        MetricEvaluation(name="freshness", score=0.8, reasoning="recent", passes=True),
    ]
    assert await reasoner.assess_user_interaction("q", [], {}, passing) is False


async def test_assess_user_interaction_true_when_any_fails(reasoner: UserQueryReasoner) -> None:
    mixed = [
        MetricEvaluation(name="completeness", score=0.3, reasoning="sparse", passes=False),
        MetricEvaluation(name="freshness", score=0.9, reasoning="recent", passes=True),
    ]
    assert await reasoner.assess_user_interaction("q", [], {}, mixed) is True


async def test_assess_user_interaction_true_when_all_fail(reasoner: UserQueryReasoner) -> None:
    failing = [
        MetricEvaluation(name="completeness", score=0.1, reasoning="", passes=False),
        MetricEvaluation(name="freshness", score=0.0, reasoning="", passes=False),
    ]
    assert await reasoner.assess_user_interaction("q", [], {}, failing) is True


# ── assess_query_results ──────────────────────────────────────────────────────

async def test_identify_user_data_metrics_returns_defaults(reasoner: UserQueryReasoner) -> None:
    metrics = reasoner._identify_user_data_metrics("q", [], {})
    # completeness + freshness + privacy (privacy added when manager is provided)
    assert len(metrics) == 3
    assert {type(m).__name__ for m in metrics} == {"CompletenessMetric", "FreshnessMetric", "PrivacyMetric"}


async def test_assess_query_results_evaluates_each_metric(reasoner: UserQueryReasoner) -> None:
    ev = MetricEvaluation(name="mock", score=0.9, reasoning="ok", passes=True)
    mock_metric = MagicMock()
    mock_metric._is_applicable.return_value = True
    mock_metric.evaluate = AsyncMock(return_value=ev)
    reasoner._metrics = [mock_metric]

    results = await reasoner.assess_query_results("q", ["data"], {})

    assert len(results) == 1
    assert results[0].name == "mock"
    mock_metric.evaluate.assert_awaited_once_with("q", ["data"], {})


async def test_assess_query_results_skips_non_applicable(reasoner: UserQueryReasoner) -> None:
    mock_metric = MagicMock()
    mock_metric._is_applicable.return_value = False
    mock_metric.evaluate = AsyncMock()
    reasoner._metrics = [mock_metric]

    results = await reasoner.assess_query_results("q", [], {})

    assert results == []
    mock_metric.evaluate.assert_not_awaited()


# ── request_user_interaction ──────────────────────────────────────────────────

async def test_request_user_interaction_appends_user_response(reasoner: UserQueryReasoner) -> None:
    failing = [MetricEvaluation(name="completeness", score=0.1, reasoning="", passes=False)]

    mock_interaction = AsyncMock()
    mock_interaction.send = AsyncMock(return_value="I prefer remote work")

    mock_method = MagicMock()
    mock_method.protocol = "stdio"
    mock_method.name = "default"
    mock_method.interact.return_value = mock_interaction

    mock_cm = AsyncMock()
    mock_cm.identify_contact_method = AsyncMock(return_value=mock_method)

    mock_store = AsyncMock()

    with (
        patch("blue_data_user_source.interaction.ContactManager", return_value=mock_cm),
        patch.object(reasoner._manager, "store_data", mock_store),
        patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value="Could you share more?")),
    ):
        data, _ = await reasoner.request_user_interaction("location?", ["existing"], {}, failing)

    assert "existing" in data
    assert "I prefer remote work" in data
    mock_interaction.start.assert_awaited_once()
    mock_interaction.stop.assert_awaited_once()


async def test_request_user_interaction_message_mentions_failing_metrics(reasoner: UserQueryReasoner) -> None:
    failing = [
        MetricEvaluation(name="completeness", score=0.1, reasoning="", passes=False),
        MetricEvaluation(name="freshness", score=0.2, reasoning="", passes=False),
    ]
    sent: list[str] = []

    mock_interaction = AsyncMock()
    mock_interaction.send = AsyncMock(side_effect=lambda msg: sent.append(msg) or "ok")

    mock_method = MagicMock()
    mock_method.protocol = "stdio"
    mock_method.name = "default"
    mock_method.interact.return_value = mock_interaction

    mock_cm = AsyncMock()
    mock_cm.identify_contact_method = AsyncMock(return_value=mock_method)

    with (
        patch("blue_data_user_source.interaction.ContactManager", return_value=mock_cm),
        patch.object(reasoner._manager, "store_data", AsyncMock()),
        patch("blue_data_user_source.reasoning.reasoner._llm_complete", AsyncMock(return_value="question")),
    ):
        await reasoner.request_user_interaction("query?", [], {}, failing)

    assert len(sent) == 1


# ── resolve_via_interaction ─────────────────────────────────────────────────────

def _mock_contact_manager(responses: list[str]) -> AsyncMock:
    mock_interaction = AsyncMock()
    mock_interaction.send = AsyncMock(side_effect=list(responses))

    mock_method = MagicMock()
    mock_method.protocol = "stdio"
    mock_method.name = "default"
    mock_method.interact.return_value = mock_interaction

    mock_cm = AsyncMock()
    mock_cm.identify_contact_method = AsyncMock(return_value=mock_method)
    return mock_cm


async def test_resolve_via_interaction_stops_once_metrics_pass(reasoner: UserQueryReasoner) -> None:
    failing = [MetricEvaluation(name="completeness", score=0.1, reasoning="", passes=False)]
    passing = [MetricEvaluation(name="completeness", score=0.9, reasoning="", passes=True)]

    # 1st call: initial assessment (fails). 2nd call: re-assessment after the
    # user's response (passes), which should stop the loop after one round.
    reasoner.assess_query_results = AsyncMock(side_effect=[failing, passing])  # type: ignore[method-assign]

    with (
        patch(
            "blue_data_user_source.interaction.ContactManager",
            return_value=_mock_contact_manager(["remote"]),
        ),
        patch.object(reasoner._manager, "store_data", AsyncMock()),
        patch(
            "blue_data_user_source.reasoning.reasoner._llm_complete",
            AsyncMock(return_value="Could you share more?"),
        ),
    ):
        new_items = await reasoner.resolve_via_interaction(
            "location?", "location?", ["existing"], {}, max_rounds=3
        )

    assert new_items == ["remote"]
    assert reasoner.assess_query_results.await_count == 2


async def test_resolve_via_interaction_stops_at_max_rounds(reasoner: UserQueryReasoner) -> None:
    failing = [MetricEvaluation(name="completeness", score=0.1, reasoning="", passes=False)]

    # Never passes, so the loop should run exactly max_rounds times.
    reasoner.assess_query_results = AsyncMock(return_value=failing)  # type: ignore[method-assign]

    with (
        patch(
            "blue_data_user_source.interaction.ContactManager",
            return_value=_mock_contact_manager(["a", "b"]),
        ),
        patch.object(reasoner._manager, "store_data", AsyncMock()),
        patch(
            "blue_data_user_source.reasoning.reasoner._llm_complete",
            AsyncMock(return_value="Could you share more?"),
        ),
    ):
        new_items = await reasoner.resolve_via_interaction(
            "location?", "location?", ["existing"], {}, max_rounds=2
        )

    assert new_items == ["a", "b"]
    # initial assessment + one re-assessment per round
    assert reasoner.assess_query_results.await_count == 3


async def test_resolve_via_interaction_no_rounds_when_metrics_already_pass(
    reasoner: UserQueryReasoner,
) -> None:
    passing = [MetricEvaluation(name="completeness", score=0.9, reasoning="", passes=True)]
    reasoner.assess_query_results = AsyncMock(return_value=passing)  # type: ignore[method-assign]

    with patch("blue_data_user_source.interaction.ContactManager") as mock_cm_cls:
        new_items = await reasoner.resolve_via_interaction(
            "location?", "location?", ["existing"], {}, max_rounds=3
        )

    assert new_items == []
    mock_cm_cls.assert_not_called()
