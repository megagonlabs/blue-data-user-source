"""Report-only querying benchmark, replayed from committed VCR cassettes.

Seeds a fresh ``UserDataManager`` with case-specific user text, then executes
the natural-language query (which may address the user as "you", "the user",
or by name) and scores result alignment against expected facts.

Never fails on a metric regression — prints and writes scores.  To record
cassettes or run live, set ``OPENAI_API_KEY``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ..common import runner, scoring
from ..common.cases import cassette_filename, load_query_cases
from ..common.reporting import render_query_table, write_detailed_log, write_json

CASES_DIR    = Path(__file__).parent / "cases"
CASSETTE_DIR = Path(__file__).parent / "cassettes"
REPORT_PATH  = Path(__file__).parent / ".reports" / "latest.json"
DETAIL_LOG   = Path(__file__).parent / ".reports" / "latest.detail.jsonl"
DEFAULT_MODEL = "gpt-4o-mini"

pytestmark = pytest.mark.vcr

_cases = {c.id: c for c in load_query_cases(CASES_DIR)}
_params = list(_cases.keys())
_collected_scores: list[scoring.QueryCaseScore] = []
_collected_results: list[runner.QueryRunResult] = []


@pytest.fixture(scope="session", autouse=True)
def _print_and_write_report():
    yield
    if _collected_scores:
        from rich.console import Console
        Console().print(render_query_table(_collected_scores))
        write_json(_collected_scores, REPORT_PATH)
        write_detailed_log(_collected_results, DETAIL_LOG)


@pytest.mark.parametrize("case_id", _params)
async def test_case(case_id: str) -> None:
    cassette_path = CASSETTE_DIR / cassette_filename(case_id)
    if not cassette_path.exists() and not os.environ.get("OPENAI_API_KEY"):
        pytest.skip(f"no cassette for {cassette_path.name!r} and OPENAI_API_KEY is unset")

    import openai

    case = _cases[case_id]
    result = await runner.run_query_case(case, DEFAULT_MODEL)
    judge_client = openai.AsyncOpenAI()
    score = await scoring.score_query_case(case, result, judge_client, DEFAULT_MODEL)
    _collected_scores.append(score)
    _collected_results.append(result)
