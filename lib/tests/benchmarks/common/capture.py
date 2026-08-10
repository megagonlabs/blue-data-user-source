"""LLM call capture for user-source benchmarks.

Wraps ``openai.AsyncOpenAI`` so that every ``chat.completions.create`` call
is recorded with latency and token counts.  Patch ``openai.AsyncOpenAI`` with
``functools.partial(InstrumentedOpenAI, real_client_cls=openai.AsyncOpenAI, sink=calls)``
*before* constructing the real client — both ``_llm_complete`` and
``KBSource.answer`` go through this same site.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


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
