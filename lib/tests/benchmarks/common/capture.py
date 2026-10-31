"""LLM call capture for user-source benchmarks.

Wraps the LLM clients so that every ``chat.completions.create`` call is
recorded with latency and token counts. The calls go through LiteLLM (#190):
``_llm_complete`` through ``blue_data_user_source.llm.AsyncClient``, and the KB's
agents (``KBSource.answer``, extraction) through ``blue_data_kb_source.llm.AsyncClient``.
``instrumented(calls)`` patches both.
"""

from __future__ import annotations

import contextlib
import functools
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

_CLIENTS = ("blue_data_user_source.llm", "blue_data_kb_source.llm")


@dataclass
class LLMCallRecord:
    model: str
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    messages: list[dict] = field(default_factory=list)


class InstrumentedOpenAI:
    def __init__(self, *args: Any, real_client_cls: type, sink: list[LLMCallRecord], **kwargs: Any) -> None:
        self._client = real_client_cls(*args, **kwargs)
        self._sink = sink
        self.chat = _InstrumentedChat(self._client.chat, sink)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _InstrumentedChat:
    def __init__(self, chat: Any, sink: list[LLMCallRecord]) -> None:
        self._chat = chat
        self._sink = sink
        self.completions = _InstrumentedCompletions(chat.completions, sink)


class _InstrumentedCompletions:
    def __init__(self, completions: Any, sink: list[LLMCallRecord]) -> None:
        self._completions = completions
        self._sink = sink

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        response = await self._completions.create(*args, **kwargs)
        elapsed = time.monotonic() - start
        usage = getattr(response, "usage", None)
        self._sink.append(LLMCallRecord(
            model=kwargs.get("model", ""),
            latency_seconds=elapsed,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
            messages=list(kwargs.get("messages") or []),
        ))
        return response


@contextlib.contextmanager
def instrumented(sink: list[LLMCallRecord]) -> Iterator[None]:
    """Record every LLM call, user-source's and the KB's, into *sink*.

    Each real client class is looked up before its patch is applied: looked up
    from inside ``__init__`` it would resolve to the wrapper and recurse.
    """
    import importlib

    with contextlib.ExitStack() as stack:
        for name in _CLIENTS:
            real = importlib.import_module(name).AsyncClient
            wrapper = functools.partial(InstrumentedOpenAI, real_client_cls=real, sink=sink)
            stack.enter_context(patch(f"{name}.AsyncClient", wrapper))
        yield
