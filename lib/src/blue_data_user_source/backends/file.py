import json
import uuid
from pathlib import Path
from typing import Any, Callable

from blue_data_user_source.interfaces import GraphSource, VectorSource


class FileGraphSource(GraphSource):
    """Property graph persisted to a single JSON file on disk."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"nodes": {}, "edges": {}}
        return json.loads(self._path.read_text())  # type: ignore[no-any-return]

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self._path)

    async def add_node(
        self,
        node_id: str,
        labels: list[str],
        properties: dict[str, Any],
    ) -> str:
        data = self._read()
        data["nodes"][node_id] = {"id": node_id, "labels": labels, "properties": properties}
        self._write(data)
        return node_id

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        return self._read()["nodes"].get(node_id)

    async def delete_node(self, node_id: str) -> None:
        data = self._read()
        data["nodes"].pop(node_id, None)
        incident = [eid for eid, e in data["edges"].items() if e["from"] == node_id or e["to"] == node_id]
        for eid in incident:
            data["edges"].pop(eid)
        self._write(data)

    async def add_edge(
        self,
        from_id: str,
        to_id: str,
        edge_type: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        edge_id = str(uuid.uuid4())
        data = self._read()
        data["edges"][edge_id] = {
            "id": edge_id,
            "from": from_id,
            "to": to_id,
            "type": edge_type,
            "properties": properties or {},
        }
        self._write(data)
        return edge_id

    async def delete_edge(self, edge_id: str) -> None:
        data = self._read()
        data["edges"].pop(edge_id, None)
        self._write(data)

    async def query_nodes(
        self,
        labels: list[str] | None = None,
        properties: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        nodes = self._read()["nodes"].values()
        results = []
        for node in nodes:
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
        data = self._read()
        results = []
        for edge in data["edges"].values():
            if edge_type and edge["type"] != edge_type:
                continue
            if direction in ("out", "both") and edge["from"] == node_id:
                neighbor = data["nodes"].get(edge["to"])
                if neighbor:
                    results.append(neighbor)
            if direction in ("in", "both") and edge["to"] == node_id:
                neighbor = data["nodes"].get(edge["from"])
                if neighbor:
                    results.append(neighbor)
        return results

    async def cypher(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("Cypher queries require Neo4jGraphSource")


class FileVectorSource(VectorSource):
    """Vector store persisted to a single file on disk (no actual embeddings — linear scan)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        return json.loads(self._path.read_text())  # type: ignore[no-any-return]

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self._path)

    async def set(
        self, key: str, text: str, metadata: dict[str, Any] | None = None
    ) -> None:
        embedding = await self._embed(text)
        data = self._read()
        data[key] = {"text": text, "embedding": embedding, "metadata": metadata or {}}
        self._write(data)

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._read().get(key)

    async def delete(self, key: str) -> None:
        data = self._read()
        data.pop(key, None)
        self._write(data)

    async def query(
        self,
        text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        data = self._read()
        if not data:
            return []
        query_embedding = await self._embed(text)
        scored = sorted(
            (
                (self._cosine_similarity(query_embedding, entry["embedding"]), key)
                for key, entry in data.items()
                if "embedding" in entry
            ),
            reverse=True,
        )
        results = [
            {**{k: v for k, v in data[key].items() if k != "embedding"}, "score": score}
            for score, key in scored[:top_k]
        ]
        if threshold is not None:
            results = self._apply_threshold(results, threshold)
        return results


def file_store_factory(
    base_dir: str | Path,
) -> Callable[[str], tuple[FileGraphSource, FileVectorSource]]:
    """Return a store factory that persists each database under base_dir/<name>/."""
    base = Path(base_dir).expanduser()

    def factory(name: str) -> tuple[FileGraphSource, FileVectorSource]:
        db_dir = base / name
        db_dir.mkdir(parents=True, exist_ok=True)
        return FileGraphSource(db_dir / "graph.json"), FileVectorSource(db_dir / "vectors.json")

    return factory
