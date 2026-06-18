from typing import Any

from blue_data_user_source.interfaces import DataRegistry, DataSource, GraphSource, VectorSource
from blue_data_user_source.types import QueryError


class UserDataRegistry(DataRegistry):
    """Per-user data registry backed by a property graph store and a vector store."""

    def __init__(self, graph_store: GraphSource, vector_store: VectorSource) -> None:
        self._graph = graph_store
        self._vector = vector_store
        self._sources: dict[str, Any] = {}

    async def register_source(self, source_id: str, source: Any) -> None:
        """Register a data source under the given identifier."""
        self._sources[source_id] = source

    async def get_source(self, source_id: str) -> Any:
        """Return the source registered under source_id, or None."""
        return self._sources.get(source_id)

    async def execute(
        self,
        query: str,
        source_id: str,
        top_k: int = 10,
        threshold: float | None = None,
    ) -> list[Any]:
        """Execute a query against the named source and return raw results."""
        source = self._sources.get(source_id)
        if source is None:
            raise QueryError(f"Source not found: {source_id}")
        if isinstance(source, VectorSource):
            return await source.query(query, top_k=top_k, threshold=threshold)
        if isinstance(source, GraphSource):
            return await source.query(query)
        return await source.query(query)

    # ── graph operations ──────────────────────────────────────────────────────

    async def add_node(
        self,
        node_id: str,
        labels: list[str],
        properties: dict[str, Any],
    ) -> str:
        return await self._graph.add_node(node_id, labels, properties)

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        return await self._graph.get_node(node_id)

    async def add_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        return await self._graph.add_edge(from_id, to_id, edge_type, properties)

    async def query_nodes(
        self,
        labels: list[str] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return await self._graph.query_nodes(labels, properties)

    async def query_neighbors(
        self,
        node_id: str,
        edge_type: str | None = None,
        direction: str = "out",
    ) -> list[dict[str, Any]]:
        return await self._graph.query_neighbors(node_id, edge_type, direction)

    async def graph_query(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return await self._graph.cypher(cypher, params)

    # ── vector operations ─────────────────────────────────────────────────────

    async def set_vector(self, key: str, text: str, metadata: dict[str, Any]) -> None:
        """Embed and store text in the vector store."""
        await self._vector.set(key, text, metadata)

    async def execute_vector(
        self,
        text: str,
        top_k: int = 10,
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a semantic similarity search against the vector store."""
        return await self._vector.query(text, top_k=top_k, threshold=threshold)
