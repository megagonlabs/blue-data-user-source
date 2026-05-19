import math
from abc import ABC, abstractmethod
from typing import Any


class DataSource(ABC):
    """Abstract base for all data sources accepted by UserDb."""

    source_type: str = "unknown"
    location: str = ""

    @abstractmethod
    async def query(self, query: str) -> list[Any]:
        """Execute a query against this source and return raw results."""


class JSONSource(ABC):
    """Abstract interface for a structured key-value store."""

    @abstractmethod
    async def set(self, key: str, value: dict[str, Any]) -> None:
        """Store or overwrite a JSON value."""

    @abstractmethod
    async def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve by key."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove a key."""

    @abstractmethod
    async def query(self, expression: str) -> list[dict[str, Any]]:
        """Query using a JSONPath or equivalent expression."""

    @abstractmethod
    async def keys(self, prefix: str | None = None) -> list[str]:
        """List all keys, optionally filtered by prefix."""


class VectorSource(ABC):
    """Abstract interface for a semantic vector store."""

    @abstractmethod
    async def set(
        self, key: str, text: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Embed and store text with optional metadata."""

    @abstractmethod
    async def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve entry by key."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove an entry."""

    @abstractmethod
    async def query(
        self,
        text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic similarity search."""

    async def _embed(self, text: str) -> list[float]:
        from llama_index.core import Settings  # type: ignore[import-untyped]
        return await Settings.embed_model.aget_text_embedding(text)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)


class DataRegistry(ABC):
    """Abstract base for data registries."""


class DataPlanner(ABC):
    """Abstract base for query planners."""
