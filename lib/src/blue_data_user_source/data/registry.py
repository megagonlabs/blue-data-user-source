from typing import Any

from blue_data_user_source.interfaces import DataRegistry, DataSource, JSONSource, VectorSource
from blue_data_user_source.types import QueryError


class UserDataRegistry(DataRegistry):
    """Per-user data registry backed by a JSON store and a vector store."""

    def __init__(self, json_store: JSONSource, vector_store: VectorSource) -> None:
        self._json = json_store
        self._vector = vector_store
        self._sources: dict[str, DataSource] = {}

    async def register_source(self, source_id: str, source: DataSource) -> None:
        """Register a user-specific data source under the given identifier."""
        self._sources[source_id] = source

    async def get_source(self, source_id: str) -> DataSource | None:
        """Return the source registered under source_id, or None."""
        return self._sources.get(source_id)

    async def execute(self, query: str, source_id: str) -> list[Any]:
        """Execute a query against the named source and return raw results."""
        source = self._sources.get(source_id)
        if source is None:
            raise QueryError(f"Source not found: {source_id}")
        return await source.query(query)

    async def execute_json(self, expression: str) -> list[dict[str, Any]]:
        """Execute a JSONPath expression against the JSON store."""
        return await self._json.query(expression)

    async def execute_vector(self, text: str, top_k: int = 10) -> list[dict[str, Any]]:
        """Execute a semantic similarity search against the vector store."""
        return await self._vector.query(text, top_k=top_k)

    async def set_json(self, key: str, value: dict[str, Any]) -> None:
        """Write a value to the JSON store."""
        await self._json.set(key, value)

    async def get_json(self, key: str) -> dict[str, Any] | None:
        """Read a single value from the JSON store."""
        return await self._json.get(key)

    async def json_keys(self, prefix: str | None = None) -> list[str]:
        """List keys in the JSON store, optionally filtered by prefix."""
        return await self._json.keys(prefix)

    async def set_vector(self, key: str, text: str, metadata: dict[str, Any]) -> None:
        """Embed and store text in the vector store."""
        await self._vector.set(key, text, metadata)
