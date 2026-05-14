from typing import Any

from blue_data_user_source.interfaces import JSONSource, VectorSource


class MemoryJsonSource(JSONSource):
    """In-memory JSON key-value store. Data is not persisted between process restarts."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def set(self, key: str, value: dict[str, Any]) -> None:
        self._data[key] = value

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def query(self, expression: str) -> list[dict[str, Any]]:
        return list(self._data.values())

    async def keys(self, prefix: str | None = None) -> list[str]:
        if prefix is not None:
            return [k for k in self._data if k.startswith(prefix)]
        return list(self._data.keys())


class MemoryVectorSource(VectorSource):
    """In-memory vector store with no actual embedding (linear scan). Not for production."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def set(
        self, key: str, text: str, metadata: dict[str, Any] | None = None
    ) -> None:
        self._data[key] = {"text": text, "metadata": metadata or {}}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def query(
        self,
        text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return list(self._data.values())[:top_k]


def memory_store_factory(name: str) -> tuple[MemoryJsonSource, MemoryVectorSource]:
    """Factory that creates a fresh in-memory store pair for a given database name."""
    return MemoryJsonSource(), MemoryVectorSource()
