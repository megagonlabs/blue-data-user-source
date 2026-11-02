"""The benchmark baseline check: warn below baseline - tolerance, never fail (#131).

The baseline is the run flagged in each module's committed history."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.benchmarks.common import baseline as bl
from tests.benchmarks.common import history
from tests.benchmarks.common.scoring import QueryCaseScore, ReasoningCaseScore

_BASELINE = {
    "model": "gpt-4o", "date": "2026-10-10", "commit": "abc1234", "run_id": "20261010",
    "tolerance": 0.15, "cases": {"freshness_stale": 0.9, "skills_by_name": 1.0},
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
    monkeypatch.setattr(bl, "load", lambda module: _BASELINE)
    scores = [ReasoningCaseScore(case_id="freshness_stale", model="gpt-4o",
                                 benchmark_type="freshness", score=0.1)]
    with pytest.warns(bl.BenchmarkRegression, match="freshness_stale"):
        bl.warn_regressions("reasoning", scores)


@pytest.fixture
def benchmarks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(history, "BENCHMARKS_DIR", tmp_path)
    return tmp_path


def _run(run_id: str, value: float, model: str = "gpt-4o") -> None:
    scores = [QueryCaseScore(case_id="skills_by_name", model=model, addressing_style="by_name",
                             hit_rate=value)]
    history.record(history.summarize("querying", scores, judge_model="j", run_id=run_id,
                                     commit="abc1234"))


def test_the_baseline_is_the_flagged_run_of_the_history(benchmarks: Path) -> None:
    _run("20261010", 1.0)
    _run("20261101", 0.2)
    assert bl.load("querying") is None  # nothing flagged: nothing compared
    history.set_baseline("querying", "20261010")
    base = bl.load("querying")
    assert base is not None
    assert (base["run_id"], base["model"], base["cases"]) == ("20261010", "gpt-4o",
                                                              {"skills_by_name": 1.0})
    later = [QueryCaseScore(case_id="skills_by_name", model="gpt-4o", addressing_style="by_name",
                            hit_rate=0.2)]
    assert len(bl.regressions("querying", later)) == 1
    assert bl.load("reasoning") is None  # each module has its own


def test_only_one_run_is_the_baseline(benchmarks: Path) -> None:
    _run("20261010", 1.0)
    _run("20261101", 0.5)
    history.set_baseline("querying", "20261010")
    history.set_baseline("querying")  # the latest
    assert [r.get("baseline", False) for r in history.load("querying")] == [False, True]
    page = (benchmarks / "querying" / "results" / "README.md").read_text()
    assert "compared with the baseline, run `20261101`" in page


def test_a_baseline_is_one_models_run(benchmarks: Path) -> None:
    scores = [QueryCaseScore(case_id="skills_by_name", model=m, addressing_style="by_name")
              for m in ("gpt-4o", "gpt-4o-mini")]
    history.record(history.summarize("querying", scores, judge_model="j", run_id="r", commit="c"))
    with pytest.raises(ValueError, match="ran 2 models"):
        history.set_baseline("querying")
    with pytest.raises(ValueError, match="no querying run 'nope'"):
        history.set_baseline("querying", "nope")


def test_a_judged_metric_case_counts_its_decision_not_its_raw_score() -> None:
    """completeness_empty *should* score 0; what regresses is the pass/fail decision."""
    right = ReasoningCaseScore(case_id="completeness_empty", model="gpt-4o", benchmark_type="completeness",
                               score=0.0, passes=False, expect_pass=False, correct=True)
    wrong = ReasoningCaseScore(case_id="completeness_empty", model="gpt-4o", benchmark_type="completeness",
                               score=0.8, passes=True, expect_pass=False, correct=False)
    assert bl.case_value(right) == 1.0
    assert bl.case_value(wrong) == 0.0
    baseline = {**_BASELINE, "cases": {"completeness_empty": 1.0}}
    assert bl.regressions("reasoning", [right], baseline) == []
    assert len(bl.regressions("reasoning", [wrong], baseline)) == 1


def test_case_value_reads_the_written_json_too() -> None:
    assert bl.case_value({"case_id": "x", "score": 0.4, "correct": None}) == 0.4
    assert bl.case_value({"case_id": "x", "score": 0.0, "correct": True}) == 1.0
    assert bl.case_value({"case_id": "x", "hit_rate": 0.75}) == 0.75
