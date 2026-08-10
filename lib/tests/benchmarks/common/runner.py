"""Benchmark runners for extraction and querying.

Both runners build a fresh ``UserDataManager`` with all-memory backends,
seed data, run the case, and return a ``RunResult``.  LLM calls are
intercepted by patching ``openai.AsyncOpenAI`` with ``InstrumentedOpenAI``
so cassette replays work without touching the network.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

from .capture import InstrumentedOpenAI, LLMCallRecord
from .cases import ExtractionCase, QueryCase

_SRC = Path(__file__).parents[3] / "src" / "blue_data_user_source" / "data"
_SCHEMA          = str(_SRC / "schema.json")
_METADATA_SCHEMA = str(_SRC / "metadata_schema.json")
_CONTACT_SCHEMA  = str(_SRC / "contact_schema.json")


async def _build_manager(user_id: str = "benchmark-user") -> Any:
    from blue_data_user_source.data.manager import UserDataManager
    mgr = UserDataManager(user_id, {"backend": "memory"})
    await mgr.build(
        schema_path=_SCHEMA,
        kb_source_props={"backend": "memory"},
        metadata_schema_path=_METADATA_SCHEMA,
        metadata_source_props={"backend": "memory"},
        contact_schema_path=_CONTACT_SCHEMA,
        contact_source_props={"backend": "memory"},
    )
    return mgr


@dataclass
class ExtractionRunResult:
    case: ExtractionCase
    model: str
    answers: dict[str, Any]         # question -> raw answer from execute_query
    metadata: dict[str, Any]        # aggregated metadata_acc
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


async def run_extraction_case(case: ExtractionCase, model: str = "gpt-4o-mini") -> ExtractionRunResult:
    """Store each input text, then run each query and collect answers."""
    import openai
    llm_calls: list[LLMCallRecord] = []
    instrumented = functools.partial(InstrumentedOpenAI, real_client_cls=openai.AsyncOpenAI, sink=llm_calls)

    with patch("openai.AsyncOpenAI", instrumented):
        manager = await _build_manager()
        for text in case.input_texts:
            await manager.store_data(text)

        answers: dict[str, Any] = {}
        all_metadata: dict[str, Any] = {}
        for qa in case.queries:
            results, meta = await manager.execute_query(qa.question)
            answers[qa.question] = results
            all_metadata.update(meta)

    return ExtractionRunResult(
        case=case,
        model=model,
        answers=answers,
        metadata=all_metadata,
        llm_calls=llm_calls,
    )


@dataclass
class QueryRunResult:
    case: QueryCase
    model: str
    results: list[Any]
    metadata: dict[str, Any]
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


async def run_query_case(case: QueryCase, model: str = "gpt-4o-mini") -> QueryRunResult:
    """Seed KB with case texts, execute the NL query, return raw results."""
    import openai
    llm_calls: list[LLMCallRecord] = []
    instrumented = functools.partial(InstrumentedOpenAI, real_client_cls=openai.AsyncOpenAI, sink=llm_calls)

    with patch("openai.AsyncOpenAI", instrumented):
        manager = await _build_manager()
        for text in case.seed_texts:
            await manager.store_data(text)
        results, metadata = await manager.execute_query(case.query)

    return QueryRunResult(
        case=case,
        model=model,
        results=results,
        metadata=metadata,
        llm_calls=llm_calls,
    )
