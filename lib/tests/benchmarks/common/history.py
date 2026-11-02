"""Committed run history, one per benchmark module: one summary line per run,
appended to ``<module>/results/history.jsonl``, and ``<module>/results/README.md``
rendered from it with trend charts — as blue-data-kb-source keeps its extraction
benchmark's.

Each full-suite live run of a module (``python -m tests.benchmarks.<module>.run``)
appends a line: the models, the headline value (the value per case the
baseline compares, see ``case_value``), its mean per group
(reasoning type, querying addressing style), the per-case values, tokens and
the commit. The per-run detail under ``<module>/.reports/`` stays out of git; the
history keeps only what is needed to see progress over time, so it is small
enough to commit and diff. One line per module is flagged ``"baseline": true``:
the run later runs are compared with (``baseline.py``).

Usage (from ``lib/``):
    python -m tests.benchmarks.common.history add tests/benchmarks/results/<run>/
    python -m tests.benchmarks.common.history add <scores.json> --module querying --note "..."
    python -m tests.benchmarks.common.history baseline --module querying [--run <run_id>]
    python -m tests.benchmarks.common.history render [--module querying]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

BENCHMARKS_DIR = Path(__file__).parent.parent
MODULES = ("extraction", "querying", "reasoning")

# What a case's group is, per module, and what the headline value means there.
_GROUP_FIELD = {"reasoning": "benchmark_type", "querying": "addressing_style"}
_HEADLINE = {
    "reasoning": "mean case value: 1/0 for a metric decision (completeness, freshness, privacy) "
                 "that is / is not the expected one, else the judged score",
    "querying": "mean hit rate: share of expected facts retrieved",
    "extraction": "mean hit rate: share of expected values found in the answers",
}
_SPARK = "▁▂▃▄▅▆▇█"
# Line colours in the trend charts, in the order the caption names them.
_PALETTE = ("#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c", "#0891b2", "#ca8a04", "#db2777")
_COLOUR_NAMES = ("blue", "green", "red", "purple", "orange", "teal", "yellow", "pink")
_CHART_RUNS = 30

HOW_TO = """
Each full live run of the {module} benchmark (`python -m tests.benchmarks.{module}.run`, from
`lib/`) appends one summary line to `history.jsonl` and regenerates this page; commit both to
record the run. Partial runs ({partial}) and runs with `--no-history` are not recorded. The
detailed report of a run stays in `{module}/.reports/` (gitignored). To record a past run or
re-render this page: `python -m tests.benchmarks.common.history add <scores.json> --module {module}
[--note ...]` and `python -m tests.benchmarks.common.history render --module {module}`.

One sample per case: treat a single case moving as noise, and a whole group moving as a signal.
"""
_PARTIAL = {"reasoning": "`--case`, `--type`"}


def results_dir(module: str) -> Path:
    return BENCHMARKS_DIR / module / "results"


def history_path(module: str) -> Path:
    return results_dir(module) / "history.jsonl"


def page_path(module: str) -> Path:
    return results_dir(module) / "README.md"


def case_value(score: Any) -> float:
    """The headline number of a case score.

    A judged metric case counts 1.0 when the metric's pass/fail decision is the
    one the case expects and 0.0 when it is not (its raw score is not "higher
    is better"); otherwise the hit rate (extraction, querying) or the judged
    score (contextualization, expansion, appropriateness).
    """
    if _get(score, "correct") is not None:
        return 1.0 if _get(score, "correct") else 0.0
    hit_rate = _get(score, "hit_rate")
    return float(hit_rate if hit_rate is not None else _get(score, "score"))


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0


def _get(score: Any, name: str) -> Any:
    return score.get(name) if isinstance(score, dict) else getattr(score, name, None)


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True,
                              cwd=Path(__file__).parent).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _answered(score: Any) -> float | None:
    """Extraction: share of questions with at least one expected value found."""
    per_query = _get(score, "per_query")
    if not per_query:
        return None
    return sum(1 for q in per_query if any(c["found"] for c in q["checks"])) / len(per_query)


def summarize(module: str, scores: list[Any], *, judge_model: str, note: str = "",
              run_id: str | None = None, date: str | None = None, commit: str | None = None,
              results: str | None = None) -> dict[str, Any]:
    """The history line for one run of *module*'s benchmark."""
    group_field = _GROUP_FIELD.get(module)
    models_per_case: dict[str, set[str]] = {}
    for s in scores:
        models_per_case.setdefault(_get(s, "case_id"), set()).add(_get(s, "model"))
    by_case: dict[str, dict[str, Any]] = {}
    by_group: dict[str, list[float]] = {}
    for s in scores:
        case_id, value = _get(s, "case_id"), round(case_value(s), 3)
        # A case run under several models gets one entry per model.
        key = case_id if len(models_per_case[case_id]) == 1 else f"{case_id} · {_get(s, 'model')}"
        entry: dict[str, Any] = {"value": value}
        if group_field:
            entry["group"] = _get(s, group_field)
            by_group.setdefault(entry["group"], []).append(value)
        if _get(s, "correct") is not None:
            entry["score"] = round(float(_get(s, "score")), 3)
        if module == "extraction":
            entry["answered"] = round(_answered(s) or 0.0, 3)
        by_case[key] = entry
    metrics: dict[str, float] = {}
    if module == "extraction":
        metrics["questions answered"] = _mean([v["answered"] for v in by_case.values()])
    return {
        "module": module,
        "run_id": run_id or datetime.now().strftime("%Y%m%d-%H%M%S"),
        "date": date or datetime.now().isoformat(timespec="seconds"),
        "commit": commit or _git("rev-parse", "--short", "HEAD"),
        "dirty": False if commit else bool(_git("status", "--porcelain", "--untracked-files=no")),
        "models": sorted({_get(s, "model") for s in scores}),
        "judge_model": judge_model,
        "cases": len(models_per_case),
        "runs": len(scores),
        "value": _mean([v["value"] for v in by_case.values()]),
        "metrics": metrics,
        "tokens": sum(int(_get(s, "prompt_tokens") or 0) + int(_get(s, "completion_tokens") or 0)
                      for s in scores),
        "latency_seconds": round(sum(float(_get(s, "latency_seconds") or 0) for s in scores), 1),
        "by_group": {g: {"cases": len(vs), "value": _mean(vs)}
                     for g, vs in sorted(by_group.items())},
        "by_case": dict(sorted(by_case.items())),
        "results": results,
        "note": note,
    }


def append(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")


def _write(module: str, runs: list[dict[str, Any]]) -> None:
    history_path(module).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in runs))


def set_baseline(module: str, run_id: str | None = None) -> dict[str, Any]:
    """Flag *run_id* (default: the latest run) as *module*'s baseline, and only it."""
    runs = load(module)
    matching = [r for r in runs if run_id in (None, r["run_id"])]
    if not matching:
        raise ValueError(f"no {module} run {run_id!r} in {history_path(module)}")
    chosen = matching[-1]
    if len(chosen["models"]) != 1:
        raise ValueError(f"{module} run {chosen['run_id']} ran {len(chosen['models'])} models; "
                         "a baseline is one model's run")
    for r in runs:
        r.pop("baseline", None)
    chosen["baseline"] = True
    _write(module, runs)
    render_page(module)
    return chosen


def baseline_run(module: str) -> dict[str, Any] | None:
    """The run of *module* flagged as its baseline, if any."""
    return next((r for r in reversed(load(module)) if r.get("baseline")), None)


def load(module: str) -> list[dict[str, Any]]:
    path = history_path(module)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def record(summary: dict[str, Any]) -> None:
    """Append *summary* to its module's history and regenerate the module's page."""
    append(history_path(summary["module"]), summary)
    render_page(summary["module"])


def render_page(module: str) -> None:
    path = page_path(module)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(module, load(module)))


# ── rendering ─────────────────────────────────────────────────────────────────

def _spark(values: list[float]) -> str:
    return "".join(_SPARK[min(int(v * len(_SPARK)), len(_SPARK) - 1)] for v in values)


def _delta(cur: float, prev: float | None) -> str:
    if prev is None or round(cur - prev, 2) == 0:
        return ""
    return f" {'▲' if cur > prev else '▼'}{abs(cur - prev):.2f}"


def _cell(series: list[float | None]) -> str:
    """Latest value, change since the previous run that had it, and a sparkline."""
    known = [v for v in series if v is not None]
    if not known:
        return "—"
    prev = known[-2] if len(known) > 1 else None
    spark = f" `{_spark(known)}`" if len(known) > 1 else ""
    return f"{known[-1]:.2f}{_delta(known[-1], prev)}{spark}"


def _label(run: dict[str, Any]) -> str:
    """``20261010-173226`` → ``261010-1732``; a date-only id stays as it is."""
    rid = run["run_id"]
    return rid[2:8] + "-" + rid[9:13] if len(rid) >= 13 else rid


def _commit(run: dict[str, Any]) -> str:
    return f"`{run.get('commit') or '?'}`{'*' if run.get('dirty') else ''}"


def _trend_chart(module: str, runs: list[dict[str, Any]]) -> list[str]:
    runs = runs[-_CHART_RUNS:]
    last = runs[-1]
    series: list[tuple[str, list[float]]] = [("all", [r["value"] for r in runs])]
    for name in last.get("metrics", {}):
        series.append((name, [r.get("metrics", {}).get(name, 0.0) for r in runs]))
    for group in last.get("by_group", {}):
        # A group a run did not have is drawn at that run's overall value, not at 0.
        series.append((group, [r.get("by_group", {}).get(group, {}).get("value", r["value"])
                               for r in runs]))
    series = series[:len(_PALETTE)]
    xs = ", ".join(f'"{_label(r)}"' for r in runs)
    palette = ", ".join(_PALETTE[:len(series)])
    out = ["```mermaid",
           '%%{init: {"themeVariables": {"xyChart": {"plotColorPalette": "' + palette + '"}}}}%%',
           "xychart-beta", f'    title "{module}: per run"', f"    x-axis [{xs}]",
           '    y-axis "value" 0 --> 1']
    out += [f"    line [{', '.join(f'{v:.2f}' for v in vals)}]" for _, vals in series]
    caption = ", ".join(f"{_COLOUR_NAMES[i]} = {name}" for i, (name, _) in enumerate(series))
    return out + ["```", "", f"*Lines: {caption}.*"]


def _group_chart(module: str, run: dict[str, Any]) -> list[str]:
    groups = sorted(run["by_group"].items(), key=lambda kv: kv[1]["value"])
    xs = ", ".join(f'"{g}"' for g, _ in groups)
    vals = ", ".join(f"{v['value']:.2f}" for _, v in groups)
    return ["```mermaid", "xychart-beta horizontal",
            f'    title "{module}, latest run: per group (weakest first)"',
            f"    x-axis [{xs}]", '    y-axis "value" 0 --> 1', f"    bar [{vals}]", "```"]


def _snapshot_link(run: dict[str, Any]) -> str:
    """A link from a module's results page to the run's committed snapshot, if any."""
    return f"[`{run['results']}/`](../../{run['results']}/)" if run.get("results") else ""


def _latest_line(run: dict[str, Any]) -> str:
    snapshot = f" · snapshot {_snapshot_link(run)}" if run.get("results") else ""
    dirty = " (uncommitted changes)" if run.get("dirty") else ""
    return (f"`{run['run_id']}` · commit `{run.get('commit') or '?'}`{dirty} · "
            f"{', '.join(run['models'])} · {run['cases']} cases, {run['runs']} runs · "
            f"judge {run['judge_model']} · {run['tokens'] / 1e3:.0f}k tokens{snapshot}"
            + (" · **baseline**" if run.get("baseline") else "")
            + (f" · *{run['note']}*" if run.get("note") else ""))


def render(module: str, runs: list[dict[str, Any]]) -> str:
    """A module's results page: latest run, trends, per-group and per-case tables, all runs."""
    how_to = HOW_TO.format(module=module, partial=_PARTIAL.get(module, "`--case`"))
    out = [f"# {module.capitalize()} benchmark results", "",
           "Generated from `history.jsonl` — do not edit by hand.", "", how_to.strip(), "",
           f"Value: {_HEADLINE[module]}.", ""]
    if not runs:
        return "\n".join(out + ["_No runs recorded yet._", ""])
    last = runs[-1]
    metrics = list(last.get("metrics", {}))
    out += ["## Latest run", "", _latest_line(last), "",
            "| | value |" + "".join(f" {m} |" for m in metrics),
            "|---|---|" + "---|" * len(metrics)]
    out.append("| **all** | " + _cell([r["value"] for r in runs]) + " |"
               + "".join(f" {_cell([r.get('metrics', {}).get(m) for r in runs])} |"
                         for m in metrics))
    for group, v in last.get("by_group", {}).items():
        series = [r.get("by_group", {}).get(group, {}).get("value") for r in runs]
        out.append(f"| {group} ({v['cases']}) | {_cell(series)} |" + " |" * len(metrics))
    out += ["", "Each cell: latest value, ▲/▼ change since the previous run, and the history as a "
            "sparkline (`▁` = 0, `█` = 1).", "", "## Trend", "", *_trend_chart(module, runs), ""]
    if len(last.get("by_group", {})) > 1:
        out += ["## By group", "", *_group_chart(module, last), ""]
    grouped = any("group" in v for v in last["by_case"].values())
    extra = "answered" if module == "extraction" else "score" if module == "reasoning" else None
    head = ["case", *(["group"] if grouped else []), "value", *([extra] if extra else [])]
    out += ["## By case (latest run)", "", "<details><summary>Show all cases</summary>", "",
            "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for key, v in sorted(last["by_case"].items(), key=lambda kv: (kv[1].get("group", ""), kv[0])):
        row = [key, *([v.get("group", "—")] if grouped else []),
               _cell([r.get("by_case", {}).get(key, {}).get("value") for r in runs])]
        if extra:
            row.append(f"{v[extra]:.2f}" if v.get(extra) is not None else "—")
        out.append("| " + " | ".join(row) + " |")
    if module == "reasoning":
        out += ["", "*score*: the metric's own reading, for a metric case; its value is whether "
                "the pass/fail decision is the expected one."]
    out += ["", "</details>", "", "## All runs", "",
            "| run | commit | models | cases | value | tokens | latency | note |",
            "|---|---|---|---|---|---|---|---|"]
    for r in reversed(runs):
        tag = "**baseline** " if r.get("baseline") else ""
        note = f"{tag}{_snapshot_link(r)} {r.get('note', '')}".strip()
        out.append(f"| {r['run_id']} | {_commit(r)} | {', '.join(r['models'])} | {r['cases']} | "
                   f"{r['value']:.2f} | {r['tokens'] / 1e3:.0f}k | {r['latency_seconds']:.0f}s | "
                   f"{note} |")
    base = next((r for r in reversed(runs) if r.get("baseline")), None)
    compared = (f"Later runs are compared with the baseline, run `{base['run_id']}`: a case more "
                f"than the tolerance below its baseline value is reported as a regression."
                if base else "No run is flagged as the baseline, so runs are not compared.")
    return "\n".join(out + ["", "`*` = run made with uncommitted changes. " + compared, ""])


# ── live runners ──────────────────────────────────────────────────────────────

def _snapshot_of(out: Path | None) -> str | None:
    """The snapshot directory (``results/<run>``, relative to the benchmarks) that a
    report written to *out* is in."""
    if out is None:
        return None
    try:
        rel = out.resolve().parent.relative_to((BENCHMARKS_DIR / "results").resolve())
    except ValueError:
        return None
    return f"results/{rel}" if rel.parts else None


def record_live_run(module: str, scores: list[Any], *, judge_model: str, note: str,
                    full: bool, enabled: bool = True, out: Path | None = None) -> None:
    """At the end of a live run: record it if it ran the whole suite, and say so.

    A report written into a snapshot directory (``--out
    tests/benchmarks/results/<run>/<module>.json``) is linked from its history line."""
    where = f"{module}/results/history.jsonl"
    if not enabled:
        print(f"--no-history: not recorded in {where}.")
    elif not full:
        print(f"Partial run: not recorded in {where}.")
    elif not scores:
        print(f"No scores: not recorded in {where}.")
    else:
        record(summarize(module, scores, judge_model=judge_model, note=note,
                         results=_snapshot_of(out)))
        print(f"Recorded in {history_path(module)} and {page_path(module)}; "
              "commit both to keep the run.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _add_snapshot(directory: Path, note: str) -> list[dict[str, Any]]:
    """One history line per module report in a committed snapshot directory."""
    run = json.loads((directory / "run.json").read_text())
    rel = str(directory.resolve().relative_to(BENCHMARKS_DIR.resolve()))
    summaries = []
    for module in MODULES:
        path = directory / f"{module}.json"
        if not path.exists():
            continue
        summaries.append(summarize(
            module, json.loads(path.read_text()), judge_model=run["judge_model"],
            note=note, run_id=run["date"].replace("-", ""), date=run["date"],
            commit=run.get("commits", {}).get(module, run["commit"]), results=rel,
        ))
    return summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="append a past run to the history")
    add.add_argument("path", type=Path,
                     help="a snapshot directory (with run.json), or a score JSON")
    add.add_argument("--module", choices=MODULES, help="the module of a score JSON")
    add.add_argument("--note", default="")
    add.add_argument("--judge-model", default="gpt-4o-mini")
    add.add_argument("--run-id", default=None, help="default: the live-<stamp> of the file name")
    add.add_argument("--commit", default=None,
                     help="commit the run was made at (default: HEAD, marked * if dirty)")
    base = sub.add_parser("baseline", help="flag a run as the module's baseline")
    base.add_argument("--module", choices=MODULES, required=True)
    base.add_argument("--run", default=None, help="the run's run_id (default: the latest run)")
    render = sub.add_parser("render", help="regenerate <module>/results/README.md")
    render.add_argument("--module", choices=MODULES, help="default: every module")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.cmd == "add":
        if args.path.is_dir():
            summaries = _add_snapshot(args.path, args.note)
        elif args.module:
            stem = args.path.stem
            stamp = stem.removeprefix("live-") if stem.startswith("live-") else None
            run_id = args.run_id or stamp
            summaries = [summarize(args.module, json.loads(args.path.read_text()),
                                   judge_model=args.judge_model, note=args.note, run_id=run_id,
                                   commit=args.commit)]
        else:
            parser.error("a score JSON needs --module")
        for summary in summaries:
            module, path = summary["module"], history_path(summary["module"])
            if summary["run_id"] in {r["run_id"] for r in load(module)}:
                print(f"{module} {summary['run_id']} is already in {path}; skipped")
                continue
            append(path, summary)
            print(f"Added {module} {summary['run_id']} to {path}")
        modules = sorted({s["module"] for s in summaries})
    elif args.cmd == "baseline":
        try:
            chosen = set_baseline(args.module, args.run)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"{args.module} baseline: run {chosen['run_id']} ({chosen['models'][0]})")
        modules = [args.module]
    else:
        modules = [args.module] if args.module else list(MODULES)
    for module in modules:
        render_page(module)
        print(f"Wrote {page_path(module)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
