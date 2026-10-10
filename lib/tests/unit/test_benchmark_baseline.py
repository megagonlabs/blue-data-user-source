"""The benchmark baseline check: warn below baseline - tolerance, never fail (#131)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.benchmarks.common import baseline as bl
from tests.benchmarks.common.scoring import QueryCaseScore, ReasoningCaseScore

_BASELINE = {
    "model": "gpt-4o", "judge_model": "gpt-4o-mini", "date": "2026-10-10", "commit": "abc1234",
    "tolerance": 0.15,
    "cases": {"reasoning/freshness_stale": 0.9, "querying/skills_by_name": 1.0},
}


def test_a_drop_beyond_the_tolerance_is_a_regression() -> None:
    scores = [ReasoningCaseScore(case_id="freshness_stale", model="gpt-4o", benchmark_type="freshness", score=0.7)]
    [message] = bl.regressions("reasoning", scores, _BASELINE)
    assert "reasoning/freshness_stale: 0.70 vs baseline 0.90" in message


def test_a_drop_within_the_tolerance_is_not() -> None:
    scores = [ReasoningCaseScore(case_id="freshness_stale", model="gpt-4o", benchmark_type="freshness", score=0.76)]
    assert bl.regressions("reasoning", scores, _BASELINE) == []


def test_hit_rate_is_the_value_for_extraction_and_querying() -> None:
    scores = [QueryCaseScore(case_id="skills_by_name", model="gpt-4o", addressing_style="name", hit_rate=0.5)]
    assert len(bl.regressions("querying", scores, _BASELINE)) == 1


def test_other_models_and_new_cases_are_not_compared() -> None:
    scores = [
        ReasoningCaseScore(case_id="freshness_stale", model="gpt-4o-mini", benchmark_type="freshness", score=0.0),
        ReasoningCaseScore(case_id="brand_new_case", model="gpt-4o", benchmark_type="freshness", score=0.0),
    ]
    assert bl.regressions("reasoning", scores, _BASELINE) == []


def test_regressions_warn_and_do_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bl, "load", lambda path=bl.BASELINE_PATH: _BASELINE)
    scores = [ReasoningCaseScore(case_id="freshness_stale", model="gpt-4o", benchmark_type="freshness", score=0.1)]
    with pytest.warns(bl.BenchmarkRegression, match="freshness_stale"):
        bl.warn_regressions("reasoning", scores)


def test_build_takes_the_run_model_s_scores_from_a_results_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bl, "BASELINE_PATH", tmp_path / "baseline.json")
    results = tmp_path / "results" / "run1"
    results.mkdir(parents=True)
    (results / "run.json").write_text(json.dumps(
        {"model": "gpt-4o", "judge_model": "gpt-4o-mini", "date": "2026-10-10", "commit": "abc1234"}))
    (results / "reasoning.json").write_text(json.dumps([
        {"case_id": "freshness_stale", "model": "gpt-4o", "score": 0.9},
        {"case_id": "freshness_stale", "model": "gpt-4o-mini", "score": 0.1},
    ]))
    (results / "querying.json").write_text(json.dumps([{"case_id": "skills_by_name", "model": "gpt-4o", "hit_rate": 1.0}]))
    (results / "extraction.json").write_text(json.dumps([]))

    built = bl.build(results)

    assert built["cases"] == {"querying/skills_by_name": 1.0, "reasoning/freshness_stale": 0.9}
    assert built["model"] == "gpt-4o" and built["commit"] == "abc1234" and built["tolerance"] == 0.15
    assert built["results"] == "results/run1"


def test_a_judged_metric_case_counts_its_decision_not_its_raw_score() -> None:
    """completeness_empty *should* score 0; what regresses is the pass/fail decision."""
    right = ReasoningCaseScore(case_id="completeness_empty", model="gpt-4o", benchmark_type="completeness",
                               score=0.0, passes=False, expect_pass=False, correct=True)
    wrong = ReasoningCaseScore(case_id="completeness_empty", model="gpt-4o", benchmark_type="completeness",
                               score=0.8, passes=True, expect_pass=False, correct=False)
    assert bl.case_value(right) == 1.0
    assert bl.case_value(wrong) == 0.0
    baseline = {**_BASELINE, "cases": {"reasoning/completeness_empty": 1.0}}
    assert bl.regressions("reasoning", [right], baseline) == []
    assert len(bl.regressions("reasoning", [wrong], baseline)) == 1


def test_case_value_reads_the_written_json_too() -> None:
    assert bl.case_value({"case_id": "x", "score": 0.4, "correct": None}) == 0.4
    assert bl.case_value({"case_id": "x", "score": 0.0, "correct": True}) == 1.0
    assert bl.case_value({"case_id": "x", "hit_rate": 0.75}) == 0.75
