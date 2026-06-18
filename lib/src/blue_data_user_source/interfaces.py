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


class GraphSource(ABC):
    """Abstract interface for a property graph store.

    The graph is governed by the schema defined in schema.txt.  Each user
    database is a logical namespace within the graph, addressed by user id.

    Node labels
    -----------
    ENTITY      – concrete instance of a class (Alice, IBM, Python)
    FACT        – reified relation between two entities
    LITERAL     – typed property value (STRING / NUMBER / DATE / BOOLEAN)
    CLASS       – category definition (PERSON, COMPANY, …)
    RELATION    – relation-type definition (WORKED_AT, HAS_SKILL, …)
    PROPERTY    – property definition (AGE, START_DATE, …)
    SOURCE      – data source metadata
    EXTRACTION  – verbatim text segment extracted from a source

    Edge types and their direction
    --------------------------------
    IS_SUBCLASS_OF   CLASS/RELATION → CLASS/RELATION
    IS_INSTANCE_OF   ENTITY → CLASS
    DEFINE_PROPERTY  CLASS/RELATION → PROPERTY
    HAS_PROPERTY     ENTITY/FACT → LITERAL
    IS_VALUE_OF      LITERAL → PROPERTY
    REPRESENTS       FACT → RELATION
    HEAD             FACT → ENTITY  (subject)
    TAIL             FACT → ENTITY  (object)
    DOMAIN           RELATION → CLASS
    RANGE            RELATION → CLASS
    EXTRACTED_FROM   ENTITY/FACT/LITERAL → EXTRACTION
    <RELATION_NAME>  ENTITY → ENTITY  (direct shortcut edge)
    """

    @abstractmethod
    async def add_node(
        self,
        node_id: str,
        labels: list[str],
        properties: dict[str, Any],
    ) -> str:
        """Add or update a node. Returns node_id."""

    @abstractmethod
    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Return node dict (keys: id, labels, properties) or None."""

    @abstractmethod
    async def delete_node(self, node_id: str) -> None:
        """Delete a node and all its incident edges."""

    @abstractmethod
    async def add_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """Add a directed edge. Returns a unique edge_id."""

    @abstractmethod
    async def delete_edge(self, edge_id: str) -> None:
        """Delete an edge by id."""

    @abstractmethod
    async def query_nodes(
        self,
        labels: list[str] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return nodes matching the given labels and/or property filters (AND semantics)."""

    @abstractmethod
    async def query_neighbors(
        self,
        node_id: str,
        edge_type: str | None = None,
        direction: str = "out",
    ) -> list[dict[str, Any]]:
        """Return neighboring nodes, optionally filtered by edge type.

        direction: "out" (default), "in", or "both".
        """

    @abstractmethod
    async def cypher(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a Cypher query. Raises NotImplementedError on non-Neo4j backends."""

    async def query(self, text: str) -> list[dict[str, Any]]:
        """Text search across node property values. Returns matching nodes."""
        text_lower = text.lower()
        all_nodes = await self.query_nodes()
        return [
            node for node in all_nodes
            if any(text_lower in str(v).lower() for v in node["properties"].values())
        ]


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
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic similarity search. Each result includes a 'score' key (cosine similarity).

        threshold: when set, accumulates the per-step percentage drop
        ((S_i - S_{i+1}) / S_i * 100) and cuts at the first pair where the running
        total exceeds the threshold (e.g. threshold=10.0 cuts when cumulative drop > 10%).
        Applied after top_k.
        """

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

    @staticmethod
    def _apply_threshold(results: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
        c_p = 0.0
        for i in range(len(results) - 1):
            s_i: float = results[i]["score"]
            p = (s_i - results[i + 1]["score"]) / s_i if s_i > 0.0 else 0.0
            p = p * 100.0  # convert to percentage
            c_p += p
            if c_p > threshold:
                return results[: i + 1]
        return results


class DataRegistry(ABC):
    """Abstract base for data registries."""


class DataPlanner(ABC):
    """Abstract base for query planners."""
