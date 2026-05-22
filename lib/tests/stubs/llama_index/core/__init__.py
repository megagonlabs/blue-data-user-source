from __future__ import annotations

import hashlib
from typing import Any


class _StubEmbedModel:
    """Returns a deterministic unit-length embedding based on text hash."""

    async def aget_text_embedding(self, text: str) -> list[float]:
        digest = hashlib.md5(text.encode()).digest()
        raw = [b / 255.0 for b in digest]
        norm = sum(x * x for x in raw) ** 0.5
        return [x / norm for x in raw]


class _Settings:
    """Stub for llama_index.core.Settings; tests replace .llm/.embed_model with mocks."""

    llm: Any = None
    embed_model: Any = _StubEmbedModel()


Settings = _Settings()
