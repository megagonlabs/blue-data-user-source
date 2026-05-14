import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blue_data_user_source.data.manager import UserDataManager
from blue_data_user_source.reasoning.metric import MetricEvaluation
from blue_data_user_source.reasoning.reasoner import UserQueryReasoner
from blue_data_user_source.source import UserSource


@pytest.fixture
def mock_llm() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
async def reasoner(user_id: str, store_factory: Any) -> UserQueryReasoner:
    mgr = UserDataManager(store_factory=store_factory)
    await mgr.create_user(user_id)
    source = UserSource.__new__(UserSource)
    source._default_database = user_id
    source._data_manager = mgr
    return UserQueryReasoner(source=source, database=user_id)


async def test_contextualize_query_returns_llm_response(
    reasoner: UserQueryReasoner, mock_llm: AsyncMock
) -> None:
    mock_llm.acomplete.return_value = "What jobs are suitable for this user?"
    with patch("blue_data_user_source.reasoning.reasoner.Settings") as mock_settings:
        mock_settings.llm = mock_llm
        result = await reasoner.contextualize_query("jobs suitable for me")
    assert result == "What jobs are suitable for this user?"


async def test_expand_query_returns_list_from_json_response(
    reasoner: UserQueryReasoner, mock_llm: AsyncMock
) -> None:
    questions = ["What skills does the user have?", "Does the user prefer remote?"]
    mock_llm.acomplete.return_value = json.dumps(questions)
    with patch("blue_data_user_source.reasoning.reasoner.Settings") as mock_settings:
        mock_settings.llm = mock_llm
        result = await reasoner.expand_query("jobs suitable for me")
    assert result == questions


async def test_expand_query_falls_back_to_original_on_invalid_json(
    reasoner: UserQueryReasoner, mock_llm: AsyncMock
) -> None:
    mock_llm.acomplete.return_value = "not valid json"
    with patch("blue_data_user_source.reasoning.reasoner.Settings") as mock_settings:
        mock_settings.llm = mock_llm
        result = await reasoner.expand_query("my query")
    assert result == ["my query"]


async def test_assess_user_verification_returns_false_when_all_metrics_pass(
    reasoner: UserQueryReasoner,
) -> None:
    passing = [
        MetricEvaluation(name="completeness", score=0.9, reasoning="enough", passes=True),
        MetricEvaluation(name="freshness", score=0.8, reasoning="recent", passes=True),
    ]
    needs = await reasoner.assess_user_verification("q", [], {}, passing)
    assert needs is False


async def test_assess_user_verification_returns_true_when_any_metric_fails(
    reasoner: UserQueryReasoner,
) -> None:
    mixed = [
        MetricEvaluation(name="completeness", score=0.3, reasoning="sparse", passes=False),
        MetricEvaluation(name="freshness", score=0.9, reasoning="recent", passes=True),
    ]
    needs = await reasoner.assess_user_verification("q", [], {}, mixed)
    assert needs is True


async def test_identify_user_data_metrics_returns_all_default_metrics(
    reasoner: UserQueryReasoner,
) -> None:
    metrics = reasoner._identify_user_data_metrics("any query", [], {})
    assert len(metrics) == 2


async def test_assess_query_results_evaluates_each_metric(
    reasoner: UserQueryReasoner,
) -> None:
    ev = MetricEvaluation(name="mock-metric", score=0.9, reasoning="ok", passes=True)
    mock_metric = MagicMock()
    mock_metric._is_applicable.return_value = True
    mock_metric.evaluate = AsyncMock(return_value=ev)
    reasoner._metrics = [mock_metric]

    results = await reasoner.assess_query_results("q", ["data"], {"provenance": []})

    assert len(results) == 1
    assert results[0].name == "mock-metric"
    mock_metric.evaluate.assert_awaited_once_with("q", ["data"], {"provenance": []})


async def test_assess_query_results_skips_non_applicable_metrics(
    reasoner: UserQueryReasoner,
) -> None:
    mock_metric = MagicMock()
    mock_metric._is_applicable.return_value = False
    mock_metric.evaluate = AsyncMock()
    reasoner._metrics = [mock_metric]

    results = await reasoner.assess_query_results("q", [], {})

    assert results == []
    mock_metric.evaluate.assert_not_awaited()


async def test_request_user_clarification_appends_user_response_to_data(
    reasoner: UserQueryReasoner,
) -> None:
    failing = [MetricEvaluation(name="completeness", score=0.1, reasoning="", passes=False)]

    mock_interaction = AsyncMock()
    mock_interaction.send = AsyncMock(return_value="I prefer remote work")

    mock_method = MagicMock()
    mock_method.interact.return_value = mock_interaction

    mock_cm_instance = AsyncMock()
    mock_cm_instance.identify_contact_method = AsyncMock(return_value=mock_method)

    with patch(
        "blue_data_user_source.interaction.ContactManager",
        return_value=mock_cm_instance,
    ):
        data, metadata = await reasoner.request_user_clarification(
            "location?", ["existing"], {"provenance": []}, failing
        )

    assert "existing" in data
    assert "I prefer remote work" in data
    mock_interaction.start.assert_awaited_once()
    mock_interaction.stop.assert_awaited_once()


async def test_request_user_clarification_message_mentions_failing_metrics(
    reasoner: UserQueryReasoner,
) -> None:
    failing = [
        MetricEvaluation(name="completeness", score=0.1, reasoning="", passes=False),
        MetricEvaluation(name="freshness", score=0.2, reasoning="", passes=False),
    ]

    sent_messages: list[str] = []

    mock_interaction = AsyncMock()
    mock_interaction.send = AsyncMock(side_effect=lambda msg: sent_messages.append(msg) or "ok")

    mock_method = MagicMock()
    mock_method.interact.return_value = mock_interaction

    mock_cm_instance = AsyncMock()
    mock_cm_instance.identify_contact_method = AsyncMock(return_value=mock_method)

    with patch(
        "blue_data_user_source.interaction.ContactManager",
        return_value=mock_cm_instance,
    ):
        await reasoner.request_user_clarification("query?", [], {}, failing)

    assert len(sent_messages) == 1
    assert "completeness" in sent_messages[0]
    assert "freshness" in sent_messages[0]
