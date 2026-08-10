"""Tests for FreshnessMetric and CompletenessMetric."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from blue_data_user_source.reasoning.metric import (
    CompletenessMetric,
    FreshnessMetric,
    MetricEvaluation,
    UserDataMetric,
)


def _meta(days_old: int = 0, node_id: str = "n1") -> dict:
    """Build a metadata_acc entry in the shape kb.answer(include_metadata=True) produces."""
    ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    return {
        node_id: {
            "id": node_id,
            "type": "ENTITY",
            "name": "alice",
            "created": ts,
            "modified": ts,
            "extraction": "Alice is 30 years old.",
            "source": "profile.txt",
            "source_original": None,
        }
    }


# ── FreshnessMetric ───────────────────────────────────────────────────────────

async def test_freshness_high_score_for_recent_data() -> None:
    ev = await FreshnessMetric().evaluate("q", [], _meta(days_old=1))
    assert ev.score > 0.9
    assert ev.passes is True
    assert ev.name == "freshness"


async def test_freshness_low_score_for_old_data() -> None:
    ev = await FreshnessMetric().evaluate("q", [], _meta(days_old=400))
    assert ev.score == 0.0
    assert ev.passes is False


async def test_freshness_zero_score_for_empty_metadata() -> None:
    ev = await FreshnessMetric().evaluate("q", [], {})
    assert ev.score == 0.0
    assert ev.passes is False
    assert "No provenance" in ev.reasoning


async def test_freshness_score_decays_with_age() -> None:
    fresh = await FreshnessMetric().evaluate("q", [], _meta(days_old=30))
    stale = await FreshnessMetric().evaluate("q", [], _meta(days_old=200))
    assert fresh.score > stale.score


async def test_freshness_zero_for_unparseable_timestamp() -> None:
    bad_meta = {"n1": {"id": "n1", "type": "ENTITY", "modified": "not-a-date", "created": "not-a-date"}}
    ev = await FreshnessMetric().evaluate("q", [], bad_meta)
    assert ev.score == 0.0
    assert ev.passes is False


async def test_freshness_uses_modified_over_created() -> None:
    now = datetime.now(timezone.utc)
    meta = {
        "n1": {
            "id": "n1",
            "type": "ENTITY",
            "created": (now - timedelta(days=300)).isoformat(),
            "modified": (now - timedelta(days=1)).isoformat(),
        }
    }
    ev = await FreshnessMetric().evaluate("q", [], meta)
    assert ev.score > 0.9


async def test_freshness_averages_multiple_nodes() -> None:
    now = datetime.now(timezone.utc)
    meta = {
        "n1": {"id": "n1", "type": "ENTITY", "modified": (now - timedelta(days=1)).isoformat()},
        "n2": {"id": "n2", "type": "ENTITY", "modified": (now - timedelta(days=364)).isoformat()},
    }
    ev = await FreshnessMetric().evaluate("q", [], meta)
    assert 0.0 < ev.score < 1.0


async def test_freshness_ignores_non_dict_metadata_values() -> None:
    meta = {"n1": "unexpected string value"}
    ev = await FreshnessMetric().evaluate("q", [], meta)
    assert ev.score == 0.0


# ── CompletenessMetric ────────────────────────────────────────────────────────

async def test_completeness_uses_llm_score() -> None:
    mock_llm = AsyncMock(return_value={"score": 0.85, "reasoning": "sufficient"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await CompletenessMetric().evaluate("What skills?", ["Python", "SQL"], {})
    assert ev.score == pytest.approx(0.85)
    assert ev.reasoning == "sufficient"
    assert ev.passes is True
    assert ev.name == "completeness"


async def test_completeness_fails_below_threshold() -> None:
    mock_llm = AsyncMock(return_value={"score": 0.2, "reasoning": "too little"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await CompletenessMetric().evaluate("q", [], {})
    assert ev.passes is False


async def test_completeness_prompt_includes_extraction_text() -> None:
    captured: list[str] = []

    async def _capture(prompt: str, **kwargs: object) -> dict:
        captured.append(prompt)
        return {"score": 0.9, "reasoning": "ok"}

    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", _capture):
        await CompletenessMetric().evaluate("q", [], _meta())

    assert captured
    assert "Alice is 30 years old." in captured[0]


async def test_completeness_prompt_includes_source_name() -> None:
    captured: list[str] = []

    async def _capture(prompt: str, **kwargs: object) -> dict:
        captured.append(prompt)
        return {"score": 0.9, "reasoning": "ok"}

    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", _capture):
        await CompletenessMetric().evaluate("q", [], _meta())

    assert "profile.txt" in captured[0]


async def test_completeness_handles_llm_error_gracefully() -> None:
    mock_llm = AsyncMock(return_value={})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await CompletenessMetric().evaluate("q", [], {})
    assert ev.score == 0.0
    assert ev.passes is False


# ── MetricEvaluation / UserDataMetric base ────────────────────────────────────

def test_metric_evaluation_dataclass_fields() -> None:
    ev = MetricEvaluation(name="test", score=0.5, reasoning="ok", passes=True)
    assert ev.name == "test"
    assert ev.score == 0.5
    assert ev.reasoning == "ok"
    assert ev.passes is True


def test_base_metric_is_applicable_always_true() -> None:
    assert UserDataMetric()._is_applicable("q", [], {}) is True


async def test_base_metric_evaluate_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await UserDataMetric().evaluate("q", [], {})
