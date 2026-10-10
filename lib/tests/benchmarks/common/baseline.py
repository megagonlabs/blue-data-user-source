"""Committed baseline scores, and the "warn below this" check against them (#131).

``baseline.json`` (next to this package) holds one score per case from a
committed live run (see ``results/``), with the model it was measured on and a
tolerance. A later run's score more than ``tolerance`` below the baseline is a
regression: pytest emits a ``BenchmarkRegression`` warning and the live runners
print it. Neither fails — the benchmarks stay report-only, because LLM-judged
scores are noisy and one bad sample should not block a change; the warning
makes the drop visible.

Regenerate the baseline from a results directory written by the runners::

    python -m tests.benchmarks.common.baseline results/<run>/
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Any

BASELINE_PATH = Path(__file__).parent.parent / "baseline.json"
MODULES = ("extraction", "querying", "reasoning")
DEFAULT_TOLERANCE = 0.15


class BenchmarkRegression(UserWarning):
    """A benchmark case scored clearly below its committed baseline."""


def case_value(score: Any) -> float:
    """The headline number of a case score.

    A judged metric case counts 1.0 when the metric's pass/fail decision is the
    one the case expects and 0.0 when it is not (its raw score is not "higher
    is better"); otherwise the hit rate (extraction, querying) or the judged
    score (contextualization, expansion, appropriateness).
    """
    get = (lambda k: score.get(k)) if isinstance(score, dict) else (lambda k: getattr(score, k, None))
    if get("correct") is not None:
        return 1.0 if get("correct") else 0.0
    return float(get("hit_rate") if get("hit_rate") is not None else get("score"))


def _field(score: Any, name: str) -> Any:
    return score[name] if isinstance(score, dict) else getattr(score, name)


def load(path: Path = BASELINE_PATH) -> dict[str, Any] | None:
    return json.loads(path.read_text()) if path.exists() else None


def regressions(module: str, scores: list[Any], baseline: dict[str, Any] | None = None) -> list[str]:
    """One message per case of *module* that scored more than the tolerance below baseline.

    Cases run on a different model than the baseline's, or without a baseline
    entry (new cases), are not compared.
    """
    baseline = load() if baseline is None else baseline
    if not baseline:
        return []
    tolerance = float(baseline.get("tolerance", DEFAULT_TOLERANCE))
    found: list[str] = []
    for score in scores:
        if _field(score, "model") != baseline.get("model"):
            continue
        key = f"{module}/{_field(score, 'case_id')}"
        if key not in baseline["cases"]:
            continue
        expected, got = float(baseline["cases"][key]), case_value(score)
        if got < expected - tolerance:
            found.append(f"{key}: {got:.2f} vs baseline {expected:.2f} (tolerance {tolerance:.2f})")
    return found


def warn_regressions(module: str, scores: list[Any]) -> list[str]:
    """Emit a ``BenchmarkRegression`` warning per regression (pytest), and return them."""
    found = regressions(module, scores)
    for message in found:
        warnings.warn(message, BenchmarkRegression, stacklevel=2)
    return found


def print_regressions(module: str, scores: list[Any]) -> None:
    """Print the comparison against the baseline at the end of a live run."""
    baseline = load()
    if not baseline:
        print("No baseline.json; nothing to compare against.")
        return
    found = regressions(module, scores, baseline)
    if found:
        print(f"{len(found)} case(s) below the committed baseline ({baseline['model']}, {baseline['date']}):")
        for message in found:
            print(f"  REGRESSION {message}")
    else:
        print(f"No regressions against the committed baseline ({baseline['model']}, {baseline['date']}).")


def build(results_dir: Path, tolerance: float = DEFAULT_TOLERANCE) -> dict[str, Any]:
    """A baseline from the ``<module>.json`` reports and ``run.json`` in *results_dir*."""
    run = json.loads((results_dir / "run.json").read_text())
    cases: dict[str, float] = {}
    for module in MODULES:
        for score in json.loads((results_dir / f"{module}.json").read_text()):
            if score["model"] == run["model"]:
                cases[f"{module}/{score['case_id']}"] = round(case_value(score), 3)
    return {
        "model": run["model"],
        "judge_model": run["judge_model"],
        "date": run["date"],
        "commit": run["commit"],
        "results": str(results_dir.relative_to(BASELINE_PATH.parent)),
        "tolerance": tolerance,
        "cases": dict(sorted(cases.items())),
    }


if __name__ == "__main__":
    target = Path(sys.argv[1]).resolve()
    BASELINE_PATH.write_text(json.dumps(build(target), indent=2) + "\n")
    print(f"Wrote {BASELINE_PATH} from {target}")
