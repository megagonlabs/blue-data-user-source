"""The "warn below this" check against each module's baseline run (#131).

A module's baseline is the run flagged ``"baseline": true`` in its committed
history (``<module>/results/history.jsonl``, see ``history.py``): its value per
case and its model. A later run's case value more than ``DEFAULT_TOLERANCE``
below the baseline's is a regression: pytest emits a ``BenchmarkRegression``
warning and the live runners print it. Neither fails — the benchmarks stay
report-only, because LLM-judged scores are noisy and one bad sample should not
block a change; the warning makes the drop visible.

Flag another run as the baseline (default: the latest)::

    python -m tests.benchmarks.common.history baseline --module <module> [--run <run_id>]
"""
from __future__ import annotations

import warnings
from typing import Any

from . import history
from .history import MODULES, case_value

__all__ = ["MODULES", "BenchmarkRegression", "case_value", "load", "regressions",
           "warn_regressions", "print_regressions"]

DEFAULT_TOLERANCE = 0.15


class BenchmarkRegression(UserWarning):
    """A benchmark case scored clearly below its committed baseline."""


def _field(score: Any, name: str) -> Any:
    return score[name] if isinstance(score, dict) else getattr(score, name)


def load(module: str) -> dict[str, Any] | None:
    """*module*'s baseline: the flagged run's model, date, commit and value per case."""
    run = history.baseline_run(module)
    if run is None:
        return None
    return {
        "model": run["models"][0], "date": run["date"][:10], "commit": run.get("commit"),
        "run_id": run["run_id"], "tolerance": DEFAULT_TOLERANCE,
        "cases": {case_id: v["value"] for case_id, v in run["by_case"].items()},
    }


def regressions(module: str, scores: list[Any],
                baseline: dict[str, Any] | None = None) -> list[str]:
    """One message per case of *module* that scored more than the tolerance below baseline.

    Cases run on a different model than the baseline's, or without a baseline
    entry (new cases), are not compared.
    """
    baseline = load(module) if baseline is None else baseline
    if not baseline:
        return []
    tolerance = float(baseline.get("tolerance", DEFAULT_TOLERANCE))
    found: list[str] = []
    for score in scores:
        if _field(score, "model") != baseline.get("model"):
            continue
        case_id = _field(score, "case_id")
        if case_id not in baseline["cases"]:
            continue
        expected, got = float(baseline["cases"][case_id]), case_value(score)
        if got < expected - tolerance:
            found.append(f"{module}/{case_id}: {got:.2f} vs baseline {expected:.2f} "
                         f"(tolerance {tolerance:.2f})")
    return found


def warn_regressions(module: str, scores: list[Any]) -> list[str]:
    """Emit a ``BenchmarkRegression`` warning per regression (pytest), and return them."""
    found = regressions(module, scores)
    for message in found:
        warnings.warn(message, BenchmarkRegression, stacklevel=2)
    return found


def print_regressions(module: str, scores: list[Any]) -> None:
    """Print the comparison against the baseline at the end of a live run."""
    baseline = load(module)
    if not baseline:
        print(f"No baseline run in {module}/results/history.jsonl; nothing to compare against.")
        return
    found = regressions(module, scores, baseline)
    against = f"baseline run {baseline['run_id']} ({baseline['model']}, {baseline['date']})"
    if found:
        print(f"{len(found)} case(s) below the {against}:")
        for message in found:
            print(f"  REGRESSION {message}")
    else:
        print(f"No regressions against the {against}.")
