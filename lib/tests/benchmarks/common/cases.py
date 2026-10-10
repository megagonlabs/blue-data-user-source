"""Case dataclasses and YAML loaders for user-source benchmarks.

Three benchmark families share this module:
  - ExtractionCase   — store user text, then query and score answer alignment
  - QueryCase        — seed KB, run NL query in different addressing styles
  - ReasoningCase    — LLM-backed reasoning assessment (contextualization,
                       expansion, completeness, freshness, privacy,
                       appropriateness)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ── ExtractionCase ────────────────────────────────────────────────────────────

@dataclass
class ExpectedAnswer:
    question: str
    expected_contains: list[str] = field(default_factory=list)


@dataclass
class ExtractionCase:
    id: str
    description: str
    input_texts: list[str]
    queries: list[ExpectedAnswer] = field(default_factory=list)
    user_name: str | None = None  # set as identity.name before seeding; see QueryCase
    source_path: Path | None = None


def _load_extraction_case(path: Path) -> ExtractionCase:
    raw = yaml.safe_load(path.read_text())
    queries = [
        ExpectedAnswer(
            question=q["question"],
            expected_contains=q.get("expected_contains", []),
        )
        for q in raw.get("queries", [])
    ]
    return ExtractionCase(
        id=raw["id"],
        description=raw.get("description", ""),
        input_texts=raw.get("input_texts", [raw.get("input_text", "")]),
        queries=queries,
        user_name=raw.get("user_name"),
        source_path=path,
    )


# ── QueryCase ─────────────────────────────────────────────────────────────────

@dataclass
class QueryCase:
    id: str
    description: str
    addressing_style: str           # "second_person" | "third_person_user" | "by_name"
    seed_texts: list[str]
    query: str
    expected_contains: list[str] = field(default_factory=list)
    # The user's own name, set as identity.name before seeding — how the
    # product learns who "you", "my" and "the user" are (onboarding asks it).
    user_name: str | None = None
    source_path: Path | None = None


def _load_query_case(path: Path) -> QueryCase:
    raw = yaml.safe_load(path.read_text())
    return QueryCase(
        id=raw["id"],
        description=raw.get("description", ""),
        addressing_style=raw.get("addressing_style", "second_person"),
        seed_texts=raw.get("seed_texts", [raw.get("seed_text", "")]),
        query=raw["query"],
        expected_contains=raw.get("expected_contains", []),
        user_name=raw.get("user_name"),
        source_path=path,
    )


# ── ReasoningCase ─────────────────────────────────────────────────────────────

@dataclass
class MetricSpec:
    name: str
    score: float
    passes: bool
    reasoning: str = ""


@dataclass
class ContactSpec:
    protocol: str
    name: str
    preference: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReasoningCase:
    """Unified case for all reasoning benchmarks.

    ``benchmark_type`` selects which field group is relevant:
      - ``"contextualization"`` — uses ``query``
      - ``"expansion"``         — uses ``query``
      - ``"completeness"``      — uses ``query``, ``results``, ``provenance``
      - ``"freshness"``         — uses ``query``, ``node_ages_days``
      - ``"privacy"``           — uses ``query``, ``results``, ``provenance``,
                                  ``user_preferences`` (keys set as
                                  ``privacy.*`` metadata)
      - ``"appropriateness"``   — uses ``query``, ``contact_protocol``,
                                  ``contact_name``, ``failing_metrics``,
                                  ``user_preferences`` (keys set as
                                  ``preferences.*`` metadata)
    """
    id: str
    description: str
    benchmark_type: str

    # contextualization / expansion / completeness / freshness / appropriateness
    query: str = ""

    # freshness — list of node ages in days; one entry = one metadata node
    node_ages_days: list[int] = field(default_factory=list)

    # completeness
    results: list[Any] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)

    # appropriateness
    contact_protocol: str = "stdio"
    contact_name: str = "default"
    failing_metrics: list[str] = field(default_factory=list)
    user_preferences: dict[str, str] = field(default_factory=dict)

    # completeness / freshness / privacy — whether the metric should pass its
    # threshold for this input. None leaves the case unjudged (raw score only).
    expect_pass: bool | None = None

    source_path: Path | None = None


def _load_reasoning_case(path: Path) -> ReasoningCase:
    raw = yaml.safe_load(path.read_text())
    return ReasoningCase(
        id=raw["id"],
        description=raw.get("description", ""),
        benchmark_type=raw["benchmark_type"],
        query=raw.get("query", ""),
        node_ages_days=raw.get("node_ages_days", []),
        results=raw.get("results", []),
        provenance=[
            {"extraction": p.get("extraction", ""), "source": p.get("source", "")}
            for p in raw.get("provenance", [])
        ],
        contact_protocol=raw.get("contact_protocol", "stdio"),
        contact_name=raw.get("contact_name", "default"),
        failing_metrics=raw.get("failing_metrics", []),
        user_preferences=raw.get("user_preferences", {}),
        expect_pass=raw.get("expect_pass"),
        source_path=path,
    )


# ── Generic loaders ───────────────────────────────────────────────────────────

def load_extraction_cases(directory: Path) -> list[ExtractionCase]:
    return [_load_extraction_case(p) for p in sorted(directory.glob("*.yaml"))]


def load_query_cases(directory: Path) -> list[QueryCase]:
    return [_load_query_case(p) for p in sorted(directory.glob("*.yaml"))]


def load_reasoning_cases(directory: Path, benchmark_type: str | None = None) -> list[ReasoningCase]:
    cases = [_load_reasoning_case(p) for p in sorted(directory.glob("*.yaml"))]
    if benchmark_type is not None:
        cases = [c for c in cases if c.benchmark_type == benchmark_type]
    return cases


def cassette_filename(case_id: str) -> str:
    return f"test_case[{case_id}].yaml"
