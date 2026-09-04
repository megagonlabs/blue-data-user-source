"""Tests for FreshnessMetric, CompletenessMetric, and PrivacyMetric."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blue_data_user_source.reasoning.metric import (
    CompletenessMetric,
    FreshnessMetric,
    MetricEvaluation,
    PrivacyMetric,
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
    mock_llm = AsyncMock(return_value={"score": 0.95, "reasoning": "data is very recent"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await FreshnessMetric().evaluate("q", [], _meta(days_old=1))
    assert ev.score > 0.9
    assert ev.passes is True
    assert ev.name == "freshness"


async def test_freshness_low_score_for_old_data() -> None:
    mock_llm = AsyncMock(return_value={"score": 0.0, "reasoning": "data is very stale"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await FreshnessMetric().evaluate("q", [], _meta(days_old=400))
    assert ev.score == 0.0
    assert ev.passes is False


async def test_freshness_zero_score_for_empty_metadata() -> None:
    # Early return before LLM — no timestamps to assess
    ev = await FreshnessMetric().evaluate("q", [], {})
    assert ev.score == 0.0
    assert ev.passes is False
    assert "No provenance" in ev.reasoning


async def test_freshness_score_decays_with_age() -> None:
    fresh_mock = AsyncMock(return_value={"score": 0.97, "reasoning": "recent"})
    stale_mock = AsyncMock(return_value={"score": 0.45, "reasoning": "old"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", fresh_mock):
        fresh = await FreshnessMetric().evaluate("q", [], _meta(days_old=30))
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", stale_mock):
        stale = await FreshnessMetric().evaluate("q", [], _meta(days_old=200))
    assert fresh.score > stale.score


async def test_freshness_zero_for_unparseable_timestamp() -> None:
    # Unparseable timestamps are skipped → no valid nodes → early return
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
    captured: list[str] = []

    async def _capture(prompt: str, **kwargs: object) -> dict:
        captured.append(prompt)
        return {"score": 0.97, "reasoning": "modified recently"}

    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", _capture):
        ev = await FreshnessMetric().evaluate("q", [], meta)

    assert ev.score > 0.9
    assert captured
    # Prompt should reflect the age based on `modified` (1 day), not `created` (300 days)
    assert "1 day(s)" in captured[0]
    assert "300 day(s)" not in captured[0]


async def test_freshness_prompt_includes_node_ages() -> None:
    captured: list[str] = []

    async def _capture(prompt: str, **kwargs: object) -> dict:
        captured.append(prompt)
        return {"score": 0.9, "reasoning": "ok"}

    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", _capture):
        await FreshnessMetric().evaluate("q", [], _meta(days_old=30))

    assert captured
    assert "30 day(s)" in captured[0]


async def test_freshness_prompt_includes_all_nodes() -> None:
    now = datetime.now(timezone.utc)
    meta = {
        "n1": {"id": "n1", "type": "ENTITY", "modified": (now - timedelta(days=1)).isoformat()},
        "n2": {"id": "n2", "type": "ENTITY", "modified": (now - timedelta(days=364)).isoformat()},
    }
    mock_llm = AsyncMock(return_value={"score": 0.5, "reasoning": "mixed ages"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await FreshnessMetric().evaluate("q", [], meta)

    assert 0.0 <= ev.score <= 1.0
    prompt = mock_llm.call_args[0][0]
    assert "n1" in prompt and "n2" in prompt


async def test_freshness_ignores_non_dict_metadata_values() -> None:
    # Non-dict values → no valid nodes → early return
    meta = {"n1": "unexpected string value"}
    ev = await FreshnessMetric().evaluate("q", [], meta)
    assert ev.score == 0.0


async def test_freshness_handles_llm_error_gracefully() -> None:
    mock_llm = AsyncMock(return_value={})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await FreshnessMetric().evaluate("q", [], _meta(days_old=1))
    assert ev.score == 0.0
    assert ev.passes is False


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


# ── PrivacyMetric ─────────────────────────────────────────────────────────────

async def test_privacy_passes_when_no_violations() -> None:
    mock_llm = AsyncMock(return_value={"score": 0.9, "reasoning": "no violations"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await PrivacyMetric().evaluate("q", ["some result"], {})
    assert ev.score == pytest.approx(0.9)
    assert ev.passes is True
    assert ev.name == "privacy"


async def test_privacy_fails_when_violations() -> None:
    mock_llm = AsyncMock(return_value={"score": 0.1, "reasoning": "sensitive data exposed"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await PrivacyMetric().evaluate("q", ["health info"], {})
    assert ev.passes is False


async def test_privacy_includes_preferences_in_prompt() -> None:
    captured: list[str] = []

    async def _capture(prompt: str, **kwargs: object) -> dict:
        captured.append(prompt)
        return {"score": 0.8, "reasoning": "ok"}

    mock_manager = MagicMock()
    mock_manager.get_metadata = lambda key: {
        "privacy.data_sharing_preference": "private",
        "privacy.sensitive_categories": ["health"],
        "privacy.retention_days": 30,
        "privacy.consent_level": "minimal",
    }.get(key)

    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", _capture):
        await PrivacyMetric(manager=mock_manager).evaluate("q", [], {})

    assert captured
    assert "private" in captured[0]
    assert "health" in captured[0]
    assert "30" in captured[0]
    assert "minimal" in captured[0]


async def test_privacy_without_manager_uses_not_specified() -> None:
    captured: list[str] = []

    async def _capture(prompt: str, **kwargs: object) -> dict:
        captured.append(prompt)
        return {"score": 0.7, "reasoning": "no prefs"}

    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", _capture):
        ev = await PrivacyMetric().evaluate("q", [], {})

    assert ev.score == pytest.approx(0.7)
    assert "not specified" in captured[0]


async def test_privacy_skips_null_metadata_keys() -> None:
    captured: list[str] = []

    async def _capture(prompt: str, **kwargs: object) -> dict:
        captured.append(prompt)
        return {"score": 0.8, "reasoning": "ok"}

    mock_manager = MagicMock()
    # Only data_sharing_preference is set; others return None
    mock_manager.get_metadata = lambda key: "team" if key == "privacy.data_sharing_preference" else None

    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", _capture):
        await PrivacyMetric(manager=mock_manager).evaluate("q", [], {})

    assert captured
    assert "team" in captured[0]
    assert "sensitive_categories" not in captured[0]


async def test_privacy_handles_llm_error_gracefully() -> None:
    mock_llm = AsyncMock(return_value={})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await PrivacyMetric().evaluate("q", [], {})
    assert ev.score == 0.0
    assert ev.passes is False


# ── PrivacyMetric consent-level threshold ──────────────────────────────────────

def _manager_with_consent(consent_level: str | None) -> MagicMock:
    mock_manager = MagicMock()
    mock_manager.get_metadata = lambda key: (
        consent_level if key == "privacy.consent_level" else None
    )
    return mock_manager


async def test_privacy_minimal_consent_raises_threshold_above_default() -> None:
    # 0.7 passes the default 0.6 threshold but not "minimal" consent's 0.8.
    mock_llm = AsyncMock(return_value={"score": 0.7, "reasoning": "borderline"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await PrivacyMetric(manager=_manager_with_consent("minimal")).evaluate("q", [], {})
    assert ev.passes is False


async def test_privacy_full_consent_lowers_threshold_below_default() -> None:
    # 0.5 fails the default 0.6 threshold but passes "full" consent's 0.4.
    mock_llm = AsyncMock(return_value={"score": 0.5, "reasoning": "acceptable"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await PrivacyMetric(manager=_manager_with_consent("full")).evaluate("q", [], {})
    assert ev.passes is True


async def test_privacy_standard_consent_matches_default_threshold() -> None:
    mock_llm = AsyncMock(return_value={"score": 0.6, "reasoning": "ok"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await PrivacyMetric(manager=_manager_with_consent("standard")).evaluate("q", [], {})
    assert ev.passes is True


async def test_privacy_unrecognized_consent_level_falls_back_to_default_threshold() -> None:
    mock_llm = AsyncMock(return_value={"score": 0.6, "reasoning": "ok"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await PrivacyMetric(manager=_manager_with_consent("unspecified-level")).evaluate("q", [], {})
    assert ev.passes is True


async def test_privacy_no_manager_uses_default_threshold() -> None:
    mock_llm = AsyncMock(return_value={"score": 0.6, "reasoning": "ok"})
    with patch("blue_data_user_source.reasoning.reasoner._llm_complete", mock_llm):
        ev = await PrivacyMetric().evaluate("q", [], {})
    assert ev.passes is True


def test_base_metric_threshold_defaults_to_class_threshold() -> None:
    assert UserDataMetric()._threshold() == UserDataMetric.THRESHOLD


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
