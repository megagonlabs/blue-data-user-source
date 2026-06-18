import uuid
from typing import Any

from blue_data_user_source.interfaces import GraphSource, VectorSource


class MemoryGraphSource(GraphSource):
    """In-memory property graph. Data is not persisted between process restarts."""

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: dict[str, dict[str, Any]] = {}

    async def add_node(
        self,
        node_id: str,
        labels: list[str],
        properties: dict[str, Any],
    ) -> str:
        self._nodes[node_id] = {"id": node_id, "labels": labels, "properties": properties}
        return node_id

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        return self._nodes.get(node_id)

    async def delete_node(self, node_id: str) -> None:
        self._nodes.pop(node_id, None)
        incident = [eid for eid, e in self._edges.items() if e["from"] == node_id or e["to"] == node_id]
        for eid in incident:
            self._edges.pop(eid)

    async def add_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        edge_id = str(uuid.uuid4())
        self._edges[edge_id] = {
            "id": edge_id,
            "from": from_id,
            "to": to_id,
            "type": edge_type,
            "properties": properties or {},
        }
        return edge_id

    async def delete_edge(self, edge_id: str) -> None:
        self._edges.pop(edge_id, None)

    async def query_nodes(
        self,
        labels: list[str] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        results = []
        for node in self._nodes.values():
            if labels and not any(lbl in node["labels"] for lbl in labels):
                continue
            if properties and not all(node["properties"].get(k) == v for k, v in properties.items()):
                continue
            results.append(node)
        return results

    async def query_neighbors(
        self,
        node_id: str,
        edge_type: str | None = None,
        direction: str = "out",
    ) -> list[dict[str, Any]]:
        results = []
        for edge in self._edges.values():
            if edge_type and edge["type"] != edge_type:
                continue
            if direction in ("out", "both") and edge["from"] == node_id:
                neighbor = self._nodes.get(edge["to"])
                if neighbor:
                    results.append(neighbor)
            if direction in ("in", "both") and edge["to"] == node_id:
                neighbor = self._nodes.get(edge["from"])
                if neighbor:
                    results.append(neighbor)
        return results

    async def cypher(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("Cypher queries require Neo4jGraphSource")


class MemoryVectorSource(VectorSource):
    """In-memory vector store with no actual embedding (linear scan). Not for production."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def set(
        self, key: str, text: str, metadata: dict[str, Any] | None = None
    ) -> None:
        embedding = await self._embed(text)
        self._data[key] = {"text": text, "embedding": embedding, "metadata": metadata or {}}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._data.get(key)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def query(
        self,
        text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        if not self._data:
            return []
        query_embedding = await self._embed(text)
        scored = sorted(
            (
                (self._cosine_similarity(query_embedding, entry["embedding"]), key)
                for key, entry in self._data.items()
                if "embedding" in entry
            ),
            reverse=True,
        )
        results = [
            {**{k: v for k, v in self._data[key].items() if k != "embedding"}, "score": score}
            for score, key in scored[:top_k]
        ]
        if threshold is not None:
            results = self._apply_threshold(results, threshold)
        return results


def memory_store_factory(name: str) -> tuple[MemoryGraphSource, MemoryVectorSource]:
    """Factory that creates a fresh in-memory store pair for a given database name."""
    return MemoryGraphSource(), MemoryVectorSource()
