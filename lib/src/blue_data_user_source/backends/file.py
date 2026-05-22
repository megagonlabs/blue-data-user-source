import json
from pathlib import Path
from typing import Any, Callable

from blue_data_user_source.interfaces import JSONSource, VectorSource


class FileJsonSource(JSONSource):
    """JSON key-value store persisted to a single file on disk."""

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

    async def set(self, key: str, value: dict[str, Any]) -> None:
        data = self._read()
        data[key] = value
        self._write(data)

    async def get(self, key: str) -> dict[str, Any] | None:
        return self._read().get(key)

    async def delete(self, key: str) -> None:
        data = self._read()
        data.pop(key, None)
        self._write(data)

    async def query(self, expression: str) -> list[dict[str, Any]]:
        return list(self._read().values())

    async def keys(self, prefix: str | None = None) -> list[str]:
        all_keys = list(self._read().keys())
        if prefix is not None:
            return [k for k in all_keys if k.startswith(prefix)]
        return all_keys


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
) -> Callable[[str], tuple[FileJsonSource, FileVectorSource]]:
    """Return a store factory that persists each database under base_dir/<name>/."""
    base = Path(base_dir).expanduser()

    def factory(name: str) -> tuple[FileJsonSource, FileVectorSource]:
        db_dir = base / name
        db_dir.mkdir(parents=True, exist_ok=True)
        return FileJsonSource(db_dir / "data.json"), FileVectorSource(db_dir / "vectors.json")

    return factory
