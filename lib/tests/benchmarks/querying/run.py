"""Live querying benchmark runner.

Seeds a fresh ``UserDataManager`` KB with case-specific user text, executes
the natural-language query (which may address the user as "you", "the user",
or by name), and scores result alignment.  Runs against the real OpenAI API
and optionally (re)records the VCR cassettes that ``test_querying_benchmark.py``
replays.

Usage (from ``lib/``, with OPENAI_API_KEY set):
    python -m tests.benchmarks.querying.run
    python -m tests.benchmarks.querying.run --model gpt-4o --model gpt-4o-mini
    python -m tests.benchmarks.querying.run --case skills_second_person
    python -m tests.benchmarks.querying.run --record
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from ..common import runner, scoring
from ..common.cases import QueryCase, cassette_filename, load_query_cases
from ..common.baseline import print_regressions
from ..common.reporting import render_query_table, write_detailed_log, write_json

CASES_DIR   = Path(__file__).parent / "cases"
REPORTS_DIR = Path(__file__).parent / ".reports"


def _default_out_paths() -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPORTS_DIR / f"live-{stamp}.json", REPORTS_DIR / f"live-{stamp}.detail.jsonl"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="append", dest="models",
                        help="Model to run (repeatable, default: gpt-4o)")
    parser.add_argument("--case", action="append", dest="case_ids",
                        help="Case id to run (repeatable, default: all)")
    parser.add_argument("--judge-model", default="gpt-4o-mini",
                        help="Model used for LLM-judge scoring (default: gpt-4o-mini)")
    parser.add_argument("--out", type=Path, default=None,
                        help="JSON score report path (default: .reports/live-<timestamp>.json)")
    parser.add_argument("--detail-out", type=Path, default=None,
                        help="Detailed log path (default: .reports/live-<timestamp>.detail.jsonl)")
    parser.add_argument("--record", action="store_true",
                        help="(Re)write cassette files for test_querying_benchmark.py")
    return parser.parse_args(argv)


def _cassette_context(case_id: str, record: bool):
    if not record:
        return contextlib.nullcontext()
    import vcr as vcrlib

    from ..common.cassettes import scrub_response

    cassette_dir = Path(__file__).parent / "cassettes"
    my_vcr = vcrlib.VCR(cassette_library_dir=str(cassette_dir), record_mode="all",
                         filter_headers=["authorization"], before_record_response=scrub_response)
    return my_vcr.use_cassette(cassette_filename(case_id))


async def _run_one(
    case: QueryCase, model: str, judge_client, judge_model: str, record: bool,
) -> tuple[runner.QueryRunResult, scoring.QueryCaseScore]:
    with _cassette_context(case.id, record):
        result = await runner.run_query_case(case, model)
    score = await scoring.score_query_case(case, result, judge_client, judge_model)
    return result, score


def _plan_work(
    args: argparse.Namespace, all_cases: dict[str, QueryCase]
) -> list[tuple[QueryCase, str]]:
    case_ids = args.case_ids or list(all_cases)
    models = args.models or ["gpt-4o"]
    return [(all_cases[cid], model) for cid in case_ids for model in models]


async def _run(
    args: argparse.Namespace,
) -> tuple[list[runner.QueryRunResult], list[scoring.QueryCaseScore]]:
    import openai
    from rich.console import Console

    all_cases = {c.id: c for c in load_query_cases(CASES_DIR)}
    work = _plan_work(args, all_cases)
    judge_client = openai.AsyncOpenAI()
    console = Console()

    total = len(work)
    console.print(f"Running {total} (case, model) combination(s)...")
    results: list[runner.QueryRunResult] = []
    scores: list[scoring.QueryCaseScore] = []
    for i, (case, model) in enumerate(work, start=1):
        console.print(
            f"[dim]\\[{i}/{total}][/dim] {case.id} · {model} · {case.addressing_style} ...", end=" "
        )
        start = time.monotonic()
        try:
            result, score = await _run_one(case, model, judge_client, args.judge_model, args.record)
        except Exception:
            console.print(f"[red]failed[/red] ({time.monotonic() - start:.1f}s)")
            raise
        console.print(f"[green]done[/green] ({time.monotonic() - start:.1f}s)")
        results.append(result)
        scores.append(score)
    return results, scores


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set; live runs need it.", file=sys.stderr)
        return 1

    default_out, default_detail = _default_out_paths()
    out_path = args.out or default_out
    detail_path = args.detail_out or default_detail

    results, scores = asyncio.run(_run(args))

    from rich.console import Console
    Console().print(render_query_table(scores))
    write_json(scores, out_path)
    write_detailed_log(results, detail_path)
    print(f"Wrote {len(scores)} score(s) to {out_path}")
    print(f"Wrote detailed log to {detail_path}")
    print_regressions("querying", scores)
    if args.record:
        print(f"Cassettes (re)written under {Path(__file__).parent / 'cassettes'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
