"""Report-only extraction benchmark, replayed from VCR cassettes recorded locally with ``run.py --record``.

Stores user-profile text into a ``UserDataManager`` KB, then queries it and
scores how much expected information is retrievable.  Never fails on a metric
regression — prints and writes scores so drift is visible.  To record
cassettes or run live, set ``OPENAI_API_KEY`` and run without VCR replay.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ..common import runner, scoring
from ..common.cases import cassette_filename, load_extraction_cases
from ..common.baseline import warn_regressions
from ..common.reporting import render_extraction_table, write_detailed_log, write_json

CASES_DIR    = Path(__file__).parent / "cases"
CASSETTE_DIR = Path(__file__).parent / "cassettes"
REPORT_PATH  = Path(__file__).parent / ".reports" / "latest.json"
DETAIL_LOG   = Path(__file__).parent / ".reports" / "latest.detail.jsonl"
# The models the committed cassettes were recorded with (the live runners' defaults).
DEFAULT_MODEL = "gpt-4o"
JUDGE_MODEL = "gpt-4o-mini"

pytestmark = pytest.mark.vcr

_cases = {c.id: c for c in load_extraction_cases(CASES_DIR)}
_params = list(_cases.keys())
_collected_scores: list[scoring.ExtractionCaseScore] = []
_collected_results: list[runner.ExtractionRunResult] = []


@pytest.fixture(scope="session", autouse=True)
def _print_and_write_report():
    yield
    if _collected_scores:
        from rich.console import Console
        Console().print(render_extraction_table(_collected_scores))
        warn_regressions("extraction", _collected_scores)
        write_json(_collected_scores, REPORT_PATH)
        write_detailed_log(_collected_results, DETAIL_LOG)


@pytest.mark.parametrize("case_id", _params)
async def test_case(case_id: str) -> None:
    cassette_path = CASSETTE_DIR / cassette_filename(case_id)
    if not cassette_path.exists() and not os.environ.get("OPENAI_API_KEY"):
        pytest.skip(f"no cassette for {cassette_path.name!r} and OPENAI_API_KEY is unset")

    import openai

    case = _cases[case_id]
    result = await runner.run_extraction_case(case, DEFAULT_MODEL)
    judge_client = openai.AsyncOpenAI()
    score = await scoring.score_extraction_case(case, result, judge_client, JUDGE_MODEL)
    _collected_scores.append(score)
    _collected_results.append(result)
