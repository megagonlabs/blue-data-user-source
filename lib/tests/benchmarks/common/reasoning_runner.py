"""Runner for LLM-backed reasoning benchmarks.

Covers six benchmark types that call ``_llm_complete`` internally:
  - ``contextualization`` — ``UserQueryReasoner.contextualize_query``
  - ``expansion``         — ``UserQueryReasoner.expand_query``
  - ``completeness``      — ``CompletenessMetric.evaluate``
  - ``freshness``         — ``FreshnessMetric.evaluate``
  - ``privacy``           — ``PrivacyMetric.evaluate``
  - ``appropriateness``   — the question-rewrite step in
                            ``UserQueryReasoner.request_user_interaction``

All types patch ``openai.AsyncOpenAI`` with ``InstrumentedOpenAI`` so VCR
cassettes are replayed transparently.
"""

from __future__ import annotations

import functools
import io
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from .capture import InstrumentedOpenAI, LLMCallRecord
from .cases import ReasoningCase

_SRC = Path(__file__).parents[3] / "src" / "blue_data_user_source" / "data"
_SCHEMA          = str(_SRC / "schema.json")
_METADATA_SCHEMA = str(_SRC / "metadata_schema.json")
_CONTACT_SCHEMA  = str(_SRC / "contact_schema.json")


async def _build_manager(user_id: str = "benchmark-user") -> Any:
    from blue_data_user_source.data.manager import (
        CLS_JSON_MEMORY,
        CLS_KB_MEMORY,
        UserDataManager,
    )
    _mem_json = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
    _mem_kb   = {"_class": CLS_KB_MEMORY,   "connection": {"protocol": "kb/memory"}}
    mgr = UserDataManager(user_id, _mem_json)
    await mgr.build(
        schema_path=_SCHEMA,
        kb_source_props=_mem_kb,
        metadata_schema_path=_METADATA_SCHEMA,
        metadata_source_props=_mem_json,
        contact_schema_path=_CONTACT_SCHEMA,
        contact_source_props=_mem_json,
        session_source_props=_mem_json,
    )
    return mgr


def _make_reasoner(manager: Any) -> Any:
    from blue_data_user_source.reasoning.reasoner import UserQueryReasoner
    return UserQueryReasoner(source=MagicMock(), manager=manager)


def _make_metric_evals(failing_metric_names: list[str]) -> list[Any]:
    from blue_data_user_source.reasoning.metric import MetricEvaluation
    evals = []
    for name in ["completeness", "freshness", "privacy"]:
        passes = name not in failing_metric_names
        score = 0.9 if passes else 0.2
        evals.append(MetricEvaluation(name=name, score=score, reasoning="benchmark", passes=passes))
    return evals


def _build_provenance_metadata(provenance: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        f"n{i}": {
            "id": f"n{i}",
            "type": "ENTITY",
            "name": f"node{i}",
            "extraction": p.get("extraction", ""),
            "source": p.get("source", "benchmark"),
            "source_original": None,
        }
        for i, p in enumerate(provenance)
    }


@dataclass
class ReasoningRunResult:
    case: ReasoningCase
    benchmark_type: str
    model: str
    output: Any                     # type depends on benchmark_type
    llm_calls: list[LLMCallRecord] = field(default_factory=list)

    @property
    def prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.llm_calls)

    @property
    def completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.llm_calls)

    @property
    def latency_seconds(self) -> float:
        return sum(c.latency_seconds for c in self.llm_calls)


_DETERMINISTIC_TYPES: set[str] = set()


async def run_reasoning_case(case: ReasoningCase, model: str = "gpt-4o-mini") -> ReasoningRunResult:
    llm_calls: list[LLMCallRecord] = []

    if case.benchmark_type in _DETERMINISTIC_TYPES:
        output = await _dispatch(case)
    else:
        import openai
        instrumented = functools.partial(InstrumentedOpenAI, real_client_cls=openai.AsyncOpenAI, sink=llm_calls)
        with patch("openai.AsyncOpenAI", instrumented):
            output = await _dispatch(case)

    return ReasoningRunResult(
        case=case,
        benchmark_type=case.benchmark_type,
        model=model,
        output=output,
        llm_calls=llm_calls,
    )


async def _dispatch(case: ReasoningCase) -> Any:
    manager = await _build_manager()
    reasoner = _make_reasoner(manager)

    if case.benchmark_type == "contextualization":
        return await reasoner.contextualize_query(case.query)

    if case.benchmark_type == "expansion":
        return await reasoner.expand_query(case.query)

    if case.benchmark_type == "freshness":
        from datetime import datetime, timedelta, timezone
        from blue_data_user_source.reasoning.metric import FreshnessMetric
        ages = case.node_ages_days  # [] really is no nodes: freshness_empty tests exactly that
        now = datetime.now(timezone.utc)
        metadata = {
            f"n{i}": {
                "id": f"n{i}",
                "type": "ENTITY",
                "modified": (now - timedelta(days=d)).isoformat(),
                "created": (now - timedelta(days=d)).isoformat(),
            }
            for i, d in enumerate(ages)
        }
        return await FreshnessMetric().evaluate(case.query, [], metadata)

    if case.benchmark_type == "completeness":
        from blue_data_user_source.reasoning.metric import CompletenessMetric
        metadata = _build_provenance_metadata(case.provenance)
        return await CompletenessMetric().evaluate(case.query, case.results, metadata)

    if case.benchmark_type == "privacy":
        from blue_data_user_source.reasoning.metric import PrivacyMetric
        for key, val in case.user_preferences.items():
            manager.set_metadata(f"privacy.{key}", val)
        metadata = _build_provenance_metadata(case.provenance)
        return await PrivacyMetric(manager=manager).evaluate(case.query, case.results, metadata)

    if case.benchmark_type == "appropriateness":
        from blue_data_user_source.interaction.contact import ContactManager, ContactMethod
        from blue_data_user_source.reasoning.metric import MetricEvaluation

        metrics = _make_metric_evals(case.failing_metrics)

        # Apply user preferences to manager metadata
        for key, val in case.user_preferences.items():
            manager.set_metadata(f"preferences.{key}", val)

        method = ContactMethod(
            protocol=case.contact_protocol,
            name=case.contact_name,
            details={},
        )

        generated_question: list[str] = []

        # Capture the LLM-generated question by intercepting interaction.send
        mock_interaction = AsyncMock()
        mock_interaction.send = AsyncMock(side_effect=lambda msg: generated_question.append(msg) or "ok")
        method_mock = MagicMock(spec=ContactMethod)
        method_mock.protocol = method.protocol
        method_mock.name = method.name
        method_mock.interact.return_value = mock_interaction

        mock_cm = AsyncMock(spec=ContactManager)
        mock_cm.identify_contact_method = AsyncMock(return_value=method_mock)

        with (
            patch("blue_data_user_source.interaction.ContactManager", return_value=mock_cm),
            patch.object(manager, "store_data", AsyncMock()),
            patch("sys.stdout", io.StringIO()),
        ):
            await reasoner.request_user_interaction(case.query, [], {}, metrics)

        return generated_question[0] if generated_question else ""

    raise ValueError(f"Unknown benchmark_type: {case.benchmark_type!r}")
