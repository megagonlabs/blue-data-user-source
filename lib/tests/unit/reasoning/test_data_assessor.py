import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from blue_data_user_source.reasoning.metric import (
    CompletenessMetric,
    FreshnessMetric,
    MetricEvaluation,
    UserDataMetric,
)


def _provenance(days_old: int = 0) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    return {"provenance": [{"source": "u1:json", "timestamp": ts, "confidence": 1.0}]}


async def test_freshness_metric_high_score_for_recent_data() -> None:
    metric = FreshnessMetric()
    evaluation = await metric.evaluate("q", [], _provenance(days_old=1))
    assert evaluation.score > 0.9
    assert evaluation.passes is True
    assert evaluation.name == "freshness"


async def test_freshness_metric_low_score_for_old_data() -> None:
    metric = FreshnessMetric()
    evaluation = await metric.evaluate("q", [], _provenance(days_old=400))
    assert evaluation.score == 0.0
    assert evaluation.passes is False


async def test_freshness_metric_zero_score_for_no_provenance() -> None:
    metric = FreshnessMetric()
    evaluation = await metric.evaluate("q", [], {})
    assert evaluation.score == 0.0
    assert evaluation.passes is False


async def test_freshness_metric_score_decays_with_age() -> None:
    metric = FreshnessMetric()
    fresh = await metric.evaluate("q", [], _provenance(days_old=30))
    stale = await metric.evaluate("q", [], _provenance(days_old=200))
    assert fresh.score > stale.score


async def test_completeness_metric_evaluate_uses_llm_score() -> None:
    mock_llm = AsyncMock()
    mock_llm.acomplete.return_value = json.dumps({"score": 0.85, "reasoning": "sufficient"})

    metric = CompletenessMetric()
    with patch("blue_data_user_source.reasoning.metric.Settings") as mock_settings:
        mock_settings.llm = mock_llm
        evaluation = await metric.evaluate("What skills?", ["Python", "SQL"], {})

    assert evaluation.score == pytest.approx(0.85)
    assert evaluation.reasoning == "sufficient"
    assert evaluation.passes is True
    assert evaluation.name == "completeness"


async def test_completeness_metric_fails_below_threshold() -> None:
    mock_llm = AsyncMock()
    mock_llm.acomplete.return_value = json.dumps({"score": 0.2, "reasoning": "too little"})

    metric = CompletenessMetric()
    with patch("blue_data_user_source.reasoning.metric.Settings") as mock_settings:
        mock_settings.llm = mock_llm
        evaluation = await metric.evaluate("q", [], {})

    assert evaluation.passes is False


async def test_metric_evaluation_dataclass_fields() -> None:
    ev = MetricEvaluation(name="test", score=0.5, reasoning="ok", passes=True)
    assert ev.name == "test"
    assert ev.score == 0.5
    assert ev.reasoning == "ok"
    assert ev.passes is True


async def test_base_metric_is_applicable_always_true() -> None:
    metric = UserDataMetric()
    assert metric._is_applicable("q", [], {}) is True


async def test_base_metric_evaluate_raises_not_implemented() -> None:
    metric = UserDataMetric()
    with pytest.raises(NotImplementedError):
        await metric.evaluate("q", [], {})


async def test_freshness_metric_assigns_zero_for_unparseable_timestamp() -> None:
    metric = FreshnessMetric()
    provenance = {"provenance": [{"source": "u1:json", "timestamp": "not-a-date", "confidence": 1.0}]}
    evaluation = await metric.evaluate("q", [], provenance)
    assert evaluation.score == 0.0
    assert evaluation.passes is False
