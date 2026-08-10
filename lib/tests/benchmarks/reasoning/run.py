"""Live reasoning benchmark runner.

Covers four LLM-backed benchmark types and one deterministic type:
  - ``contextualization`` — scores query rewrite precision
  - ``expansion``         — scores sub-question relevance and coverage
  - ``completeness``      — reports LLM-assigned completeness score
  - ``appropriateness``   — scores whether the generated question suits the channel
  - ``freshness``         — deterministic; runs without an API key or cassette

Runs against the real OpenAI API for LLM-backed cases and optionally
(re)records the VCR cassettes that ``test_reasoning_benchmark.py`` replays.

Usage (from ``lib/``, with OPENAI_API_KEY set):
    python -m tests.benchmarks.reasoning.run
    python -m tests.benchmarks.reasoning.run --model gpt-4o --model gpt-4o-mini
    python -m tests.benchmarks.reasoning.run --case ctx_career_query
    python -m tests.benchmarks.reasoning.run --type contextualization --type expansion
    python -m tests.benchmarks.reasoning.run --record
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

from ..common import reasoning_runner as rr
from ..common import scoring
from ..common.cases import ReasoningCase, cassette_filename, load_reasoning_cases
from ..common.reporting import render_reasoning_table, write_detailed_log, write_json

CASES_DIR   = Path(__file__).parent / "cases"
REPORTS_DIR = Path(__file__).parent / ".reports"

_DETERMINISTIC_TYPES = rr._DETERMINISTIC_TYPES


def _default_out_paths() -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPORTS_DIR / f"live-{stamp}.json", REPORTS_DIR / f"live-{stamp}.detail.jsonl"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", action="append", dest="models",
                        help="Model to run for LLM-backed cases (repeatable, default: gpt-4o)")
    parser.add_argument("--case", action="append", dest="case_ids",
                        help="Case id to run (repeatable, default: all)")
    parser.add_argument("--type", action="append", dest="types",
                        choices=["contextualization", "expansion", "completeness", "freshness", "appropriateness"],
                        help="Benchmark type to run (repeatable, default: all)")
    parser.add_argument("--judge-model", default="gpt-4o-mini",
                        help="Model used for LLM-judge scoring (default: gpt-4o-mini)")
    parser.add_argument("--out", type=Path, default=None,
                        help="JSON score report path (default: .reports/live-<timestamp>.json)")
    parser.add_argument("--detail-out", type=Path, default=None,
                        help="Detailed log path (default: .reports/live-<timestamp>.detail.jsonl)")
    parser.add_argument("--record", action="store_true",
                        help="(Re)write cassette files for test_reasoning_benchmark.py")
    return parser.parse_args(argv)


def _cassette_context(case: ReasoningCase, record: bool):
    if not record or case.benchmark_type in _DETERMINISTIC_TYPES:
        return contextlib.nullcontext()
    import vcr as vcrlib

    cassette_dir = Path(__file__).parent / "cassettes"
    my_vcr = vcrlib.VCR(cassette_library_dir=str(cassette_dir), record_mode="all",
                         filter_headers=["authorization"])
    return my_vcr.use_cassette(cassette_filename(case.id))


async def _run_one(
    case: ReasoningCase, model: str, judge_client, judge_model: str, record: bool,
) -> tuple[rr.ReasoningRunResult, scoring.ReasoningCaseScore]:
    with _cassette_context(case, record):
        result = await rr.run_reasoning_case(case, model)
    jc = None if case.benchmark_type in _DETERMINISTIC_TYPES else judge_client
    score = await scoring.score_reasoning_case(case, result, jc, judge_model)
    return result, score


def _plan_work(
    args: argparse.Namespace, all_cases: dict[str, ReasoningCase]
) -> list[tuple[ReasoningCase, str]]:
    case_ids = args.case_ids or list(all_cases)
    models = args.models or ["gpt-4o"]
    allowed_types = set(args.types) if args.types else None
    work: list[tuple[ReasoningCase, str]] = []
    for cid in case_ids:
        case = all_cases[cid]
        if allowed_types and case.benchmark_type not in allowed_types:
            continue
        if case.benchmark_type in _DETERMINISTIC_TYPES:
            work.append((case, "deterministic"))
        else:
            for model in models:
                work.append((case, model))
    return work


async def _run(
    args: argparse.Namespace,
) -> tuple[list[rr.ReasoningRunResult], list[scoring.ReasoningCaseScore]]:
    from rich.console import Console

    all_cases = {c.id: c for c in load_reasoning_cases(CASES_DIR)}
    work = _plan_work(args, all_cases)
    has_llm = any(case.benchmark_type not in _DETERMINISTIC_TYPES for case, _ in work)
    judge_client = None
    if has_llm:
        import openai
        judge_client = openai.AsyncOpenAI()
    console = Console()

    total = len(work)
    console.print(f"Running {total} case(s)...")
    results: list[rr.ReasoningRunResult] = []
    scores: list[scoring.ReasoningCaseScore] = []
    for i, (case, model) in enumerate(work, start=1):
        label = f"{case.id} [{case.benchmark_type}] · {model}"
        console.print(f"[dim]\\[{i}/{total}][/dim] {label} ...", end=" ")
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
    needs_llm = not args.types or any(t not in _DETERMINISTIC_TYPES for t in args.types)
    if needs_llm and not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set; live runs need it for LLM-backed cases.", file=sys.stderr)
        return 1

    default_out, default_detail = _default_out_paths()
    out_path = args.out or default_out
    detail_path = args.detail_out or default_detail

    results, scores = asyncio.run(_run(args))

    from rich.console import Console
    Console().print(render_reasoning_table(scores))
    write_json(scores, out_path)
    write_detailed_log(results, detail_path)
    print(f"Wrote {len(scores)} score(s) to {out_path}")
    print(f"Wrote detailed log to {detail_path}")
    if args.record:
        print(f"Cassettes (re)written under {Path(__file__).parent / 'cassettes'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
