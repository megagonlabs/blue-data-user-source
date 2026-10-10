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
        if case.user_name:
            manager.set_metadata("identity.name", case.user_name)
        for text in case.input_texts:
            await manager.store_data(text)

        answers: dict[str, Any] = {}
        all_metadata: dict[str, Any] = {}
        for qa in case.queries:
            results, meta = await _query_like_user_source(manager, qa.question, model)
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


async def _query_like_user_source(manager: Any, query: str, model: str) -> tuple[list[Any], dict[str, Any]]:
    """Phases 1-2 of ``UserSource._run_query``: rewrite the query (resolving
    "you" / "the user" to the user's name), expand it into sub-questions, and
    retrieve for each. Calling ``manager.execute_query`` on the raw query, as
    this runner used to, skipped the rewrite, so the addressing-style cases
    never tested addressing (#131).

    Assessment, clarification and answer synthesis are left out: the querying
    benchmark scores what retrieval finds.
    """
    import asyncio

    from blue_data_user_source.reasoning.reasoner import UserQueryReasoner

    reasoner = UserQueryReasoner(source=None, manager=manager, model=model)  # type: ignore[arg-type]
    rewritten = await reasoner.contextualize_query(query)
    questions = [*await reasoner.expand_query(rewritten), rewritten]
    outcomes = await asyncio.gather(*[manager.execute_query(q) for q in questions])
    results = [item for data, _ in outcomes for item in data]
    metadata: dict[str, Any] = {}
    for _, meta in outcomes:
        metadata.update(meta)
    return results, metadata


async def run_query_case(case: QueryCase, model: str = "gpt-4o-mini") -> QueryRunResult:
    """Seed KB with case texts, execute the NL query, return raw results."""
    import openai
    llm_calls: list[LLMCallRecord] = []
    instrumented = functools.partial(InstrumentedOpenAI, real_client_cls=openai.AsyncOpenAI, sink=llm_calls)

    with patch("openai.AsyncOpenAI", instrumented):
        manager = await _build_manager()
        if case.user_name:
            manager.set_metadata("identity.name", case.user_name)
        for text in case.seed_texts:
            await manager.store_data(text)
        results, metadata = await _query_like_user_source(manager, case.query, model)

    return QueryRunResult(
        case=case,
        model=model,
        results=results,
        metadata=metadata,
        llm_calls=llm_calls,
    )
