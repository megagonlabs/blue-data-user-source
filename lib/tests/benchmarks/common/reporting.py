"""Benchmark report rendering and serialisation.

``render_*_table`` returns a ``rich.table.Table`` ready for console output.
``write_json`` serialises score dataclasses to a JSON file (auto-creates
parent directories).  ``write_detailed_log`` writes one JSON object per line
(JSONL) with the full run result for post-hoc analysis.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any


def _to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    return obj


def write_json(scores: list[Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([_to_dict(s) for s in scores], indent=2))


def write_detailed_log(results: list[Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(_to_dict(r)) for r in results]
    path.write_text("\n".join(lines))


def render_extraction_table(scores: list[Any]) -> Any:
    from rich.table import Table
    t = Table(title="Extraction Benchmark", show_lines=True)
    t.add_column("Case ID")
    t.add_column("Hit Rate", justify="right")
    t.add_column("Prompt tok", justify="right")
    t.add_column("Compl tok", justify="right")
    t.add_column("Latency (s)", justify="right")
    for s in scores:
        t.add_row(
            s.case_id,
            f"{s.hit_rate:.2f}",
            str(s.prompt_tokens),
            str(s.completion_tokens),
            f"{s.latency_seconds:.2f}",
        )
    return t


def render_query_table(scores: list[Any]) -> Any:
    from rich.table import Table
    t = Table(title="Querying Benchmark", show_lines=True)
    t.add_column("Case ID")
    t.add_column("Style")
    t.add_column("Hit Rate", justify="right")
    t.add_column("Prompt tok", justify="right")
    t.add_column("Compl tok", justify="right")
    t.add_column("Latency (s)", justify="right")
    for s in scores:
        t.add_row(
            s.case_id,
            s.addressing_style,
            f"{s.hit_rate:.2f}",
            str(s.prompt_tokens),
            str(s.completion_tokens),
            f"{s.latency_seconds:.2f}",
        )
    return t


def render_reasoning_table(scores: list[Any]) -> Any:
    from rich.table import Table
    t = Table(title="Reasoning Benchmark", show_lines=True)
    t.add_column("Case ID")
    t.add_column("Type")
    t.add_column("Score", justify="right")
    t.add_column("Score 2", justify="right")
    t.add_column("Reasoning")
    t.add_column("Prompt tok", justify="right")
    t.add_column("Latency (s)", justify="right")
    for s in scores:
        t.add_row(
            s.case_id,
            s.benchmark_type,
            f"{s.score:.2f}",
            f"{s.secondary_score:.2f}" if s.secondary_score is not None else "—",
            s.reasoning[:80],
            str(s.prompt_tokens),
            f"{s.latency_seconds:.2f}",
        )
    return t
