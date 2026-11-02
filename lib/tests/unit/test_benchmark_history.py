"""The committed benchmark run history of each module, and the results page
rendered from it."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.benchmarks.common import history
from tests.benchmarks.common.scoring import (
    ExtractionCaseScore,
    QueryCaseScore,
    ReasoningCaseScore,
)


@pytest.fixture(autouse=True)
def results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Benchmark directories of the test's own, never the committed ones."""
    monkeypatch.setattr(history, "BENCHMARKS_DIR", tmp_path)
    return tmp_path


def _reasoning(stale: float = 0.1, ctx: float = 0.8) -> list[ReasoningCaseScore]:
    return [
        ReasoningCaseScore(case_id="freshness_stale", model="gpt-4o", benchmark_type="freshness",
                           score=stale, passes=stale >= 0.5, expect_pass=False,
                           correct=stale < 0.5, prompt_tokens=10, completion_tokens=5),
        ReasoningCaseScore(case_id="ctx_skills", model="gpt-4o", benchmark_type="contextualization",
                           score=ctx, prompt_tokens=20, completion_tokens=5),
    ]


def test_a_reasoning_line_holds_the_baseline_value_per_case_and_group() -> None:
    line = history.summarize("reasoning", _reasoning(), judge_model="gpt-4o-mini", commit="abc1234")
    assert line["module"] == "reasoning" and line["models"] == ["gpt-4o"]
    # A metric case counts its decision, not its raw score; its raw score is kept.
    assert line["by_case"]["freshness_stale"] == {"value": 1.0, "group": "freshness", "score": 0.1}
    assert line["by_case"]["ctx_skills"] == {"value": 0.8, "group": "contextualization"}
    assert line["by_group"] == {"contextualization": {"cases": 1, "value": 0.8},
                                "freshness": {"cases": 1, "value": 1.0}}
    assert (line["value"], line["tokens"]) == (0.9, 40)
    assert (line["commit"], line["dirty"]) == ("abc1234", False)


def test_an_extraction_line_counts_the_questions_answered() -> None:
    score = ExtractionCaseScore(case_id="basic", model="gpt-4o", hit_rate=0.5, per_query=[
        {"question": "q1", "checks": [{"found": True}, {"found": False}]},
        {"question": "q2", "checks": [{"found": False}]},
    ])
    line = history.summarize("extraction", [score], judge_model="j", commit="c")
    assert line["by_case"]["basic"] == {"value": 0.5, "answered": 0.5}
    assert line["metrics"] == {"questions answered": 0.5} and line["by_group"] == {}


def test_a_case_run_under_two_models_has_an_entry_per_model() -> None:
    scores = [QueryCaseScore(case_id="by_name", model=m, addressing_style="by_name", hit_rate=h)
              for m, h in (("gpt-4o", 1.0), ("gpt-4o-mini", 0.0))]
    line = history.summarize("querying", scores, judge_model="j", commit="c")
    assert set(line["by_case"]) == {"by_name · gpt-4o", "by_name · gpt-4o-mini"}
    assert line["cases"] == 1 and line["runs"] == 2


def test_the_page_shows_each_modules_trend_and_change(results: Path) -> None:
    history.record(history.summarize("reasoning", _reasoning(ctx=0.8), judge_model="j",
                                     run_id="20261101-100000", commit="aaa1111"))
    history.record(history.summarize("reasoning", _reasoning(ctx=0.4), judge_model="j",
                                     run_id="20261102-100000", commit="bbb2222", note="worse"))
    page = (results / "reasoning" / "results" / "README.md").read_text()
    assert len(history.load("reasoning")) == 2 and history.load("querying") == []
    assert page.startswith("# Reasoning benchmark results")
    assert not (results / "querying" / "results").exists()
    assert "| contextualization (1) | 0.40 ▼0.40 `▇▄` |" in page
    assert 'x-axis ["261101-1000", "261102-1000"]' in page and "line [0.90, 0.70]" in page
    assert "*worse*" in page and "`bbb2222`" in page


def test_an_empty_history_renders() -> None:
    assert "_No runs recorded yet._" in history.render("querying", [])


@pytest.mark.parametrize("full, enabled", [(False, True), (True, False)])
def test_partial_and_opted_out_runs_are_not_recorded(results: Path, full: bool,
                                                     enabled: bool) -> None:
    history.record_live_run("reasoning", _reasoning(), judge_model="j", note="",
                            full=full, enabled=enabled)
    assert history.load("reasoning") == []


def test_a_full_run_is_recorded_and_linked_to_its_snapshot(results: Path) -> None:
    out = results / "results" / "2026-11-02-gpt-4o" / "reasoning.json"
    history.record_live_run("reasoning", _reasoning(), judge_model="j", note="n", full=True,
                            out=out)
    [line] = history.load("reasoning")
    assert line["results"] == "results/2026-11-02-gpt-4o"
    page = (results / "reasoning" / "results" / "README.md").read_text()
    assert "[`results/2026-11-02-gpt-4o/`](../../results/2026-11-02-gpt-4o/)" in page
    history.record_live_run("reasoning", _reasoning(), judge_model="j", note="", full=True,
                            out=Path("/elsewhere/live.json"))
    assert history.load("reasoning")[-1]["results"] is None


def test_a_snapshot_is_added_once_per_module(results: Path) -> None:
    snapshot = results / "results" / "2026-10-10-gpt-4o"
    snapshot.mkdir(parents=True)
    (snapshot / "run.json").write_text(json.dumps({
        "model": "gpt-4o", "judge_model": "gpt-4o-mini", "date": "2026-10-10", "commit": "421622f",
        "commits": {"reasoning": "d00f477"},
    }))
    (snapshot / "reasoning.json").write_text(json.dumps(
        [{"case_id": "c", "model": "gpt-4o", "benchmark_type": "expansion", "score": 0.5}]))
    (snapshot / "querying.json").write_text(json.dumps(
        [{"case_id": "q", "model": "gpt-4o", "addressing_style": "by_name", "hit_rate": 1.0}]))
    assert history.main(["add", str(snapshot)]) == 0
    assert history.main(["add", str(snapshot)]) == 0  # already recorded: skipped
    lines = history.load("querying") + history.load("reasoning")
    assert [(r["module"], r["commit"], r["run_id"]) for r in lines] == [
        ("querying", "421622f", "20261010"), ("reasoning", "d00f477", "20261010"),
    ]
    assert all(r["results"] == "results/2026-10-10-gpt-4o" for r in lines)
    assert history.load("extraction") == []  # the snapshot has no extraction report


@pytest.mark.parametrize("status, dirty", [
    ("", False),
    # An earlier run of another module rewrote its results: the code is still clean.
    (" M lib/tests/benchmarks/querying/results/README.md\n"
     " M lib/tests/benchmarks/reasoning/results/history.jsonl", False),
    (" M lib/src/blue_data_user_source/llm.py\n"
     " M lib/tests/benchmarks/querying/results/README.md", True),
    (" M lib/tests/benchmarks/common/history.py", True),
])
def test_only_code_changes_make_a_run_dirty(monkeypatch: pytest.MonkeyPatch, status: str,
                                            dirty: bool) -> None:
    # _git strips its output, so the first line has lost its leading space.
    monkeypatch.setattr(history, "_git", lambda *args: status.strip())
    assert history._dirty() is dirty
