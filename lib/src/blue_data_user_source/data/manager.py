import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from llama_index.core import Settings  # type: ignore[import-untyped]

from blue_data_user_source.interfaces import DataSource, JSONSource, VectorSource
from blue_data_user_source.data.planner import UserDataPlanner
from blue_data_user_source.data.registry import UserDataRegistry
from blue_data_user_source.types import ImportError

StoreFactory = Callable[[str], tuple[JSONSource, VectorSource]]


class UserDataManager:
    """Manages all data sources for a user database through a UserDataRegistry."""

    def __init__(self, store_factory: StoreFactory | None) -> None:
        self._store_factory = store_factory
        self._registries: dict[str, UserDataRegistry] = {}

    async def create_user(self, name: str) -> None:
        """Initialize JSON and vector stores for a new user database."""
        if self._store_factory is None:
            raise ValueError(
                "No store_factory configured. Pass 'store_factory' in UserSource properties."
            )
        json_store, vector_store = self._store_factory(name)
        registry = UserDataRegistry(json_store, vector_store)

        await registry.register_source(f"{name}:json", json_store)
        await registry.register_source(f"{name}:vector", vector_store)

        self._registries[name] = registry

    async def _ensure_loaded(self, database: str) -> UserDataRegistry:
        if database not in self._registries:
            await self.create_user(database)
        return self._registries[database]

    async def execute_query(
        self, query: str, database: str
    ) -> tuple[list[Any], dict[str, Any]]:
        """Execute a query and return (results, metadata) including provenance."""
        registry = await self._ensure_loaded(database)
        planner = UserDataPlanner(registry)
        plan = await planner.plan(query, database)

        aggregated: list[Any] = []
        provenance: list[dict[str, Any]] = []

        for step in plan:
            raw = await registry.execute(step.subquery, step.source_id)
            aggregated.extend(raw)
            provenance.append(
                {
                    "source": step.source_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "confidence": 1.0,
                }
            )

        metadata: dict[str, Any] = {"provenance": provenance}
        return aggregated, metadata

    async def import_source(
        self,
        source: DataSource,
        database: str,
        queries: list[str] | None = None,
    ) -> None:
        """Register a source (Type 1) or extract data from it (Type 2)."""
        registry = await self._ensure_loaded(database)
        source_id = str(uuid.uuid4())
        await registry.register_source(source_id, source)

        if queries is None:
            await self._persist_source_metadata(registry, database, source, source_id, [])
        else:
            for query in queries:
                try:
                    raw = await registry.execute(query, source_id)
                    extracted = await self._llm_extract(query, raw)
                    attr_name = await self._llm_attribute_name(query)
                except Exception as exc:
                    raise ImportError(f"Query over source failed: {exc}") from exc
                await self._write_data_entry(registry, database, attr_name, extracted, source_id)
            await self._persist_source_metadata(registry, database, source, source_id, queries)

    async def store_data(
        self,
        database: str,
        key: str,
        value: Any,
        source_id: str = "interaction",
    ) -> None:
        """Write a data entry to the user DB JSON store."""
        registry = await self._ensure_loaded(database)
        await self._write_data_entry(registry, database, key, self._normalize_to_list(value), source_id)

    async def _llm_extract(self, query: str, raw_content: list[Any]) -> list[Any]:
        """Use LLM to extract query-relevant values from source content as a flat list."""
        llm = Settings.llm
        content_str = "\n".join(str(item) for item in raw_content)
        prompt = (
            f"Extract information relevant to the following query from the content below.\n"
            f"Query: {query}\n\n"
            f"Content:\n{content_str}\n\n"
            "Return a JSON array of the extracted values only. Do not wrap them in an object."
        )
        response = await llm.acomplete(prompt)
        result_str = str(response).strip()
        try:
            parsed = json.loads(result_str)
        except (json.JSONDecodeError, ValueError):
            return [result_str]
        return self._normalize_to_list(parsed)

    @staticmethod
    def _normalize_to_list(value: Any) -> list[Any]:
        """Flatten an LLM extraction result to a plain list of values."""
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            inner = list(value.values())
            if len(inner) == 1 and isinstance(inner[0], list):
                return inner[0]
            return inner
        return [value]

    async def _llm_attribute_name(self, query: str) -> str:
        """Derive a snake_case attribute name from a query following relational schema conventions."""
        llm = Settings.llm
        prompt = (
            f"Convert the following query into a concise snake_case attribute name suitable "
            f"for a relational database column (1-4 words, no verbs, noun-based, lowercase).\n"
            f"Query: {query}\n\n"
            "Return only the attribute name, nothing else."
        )
        response = await llm.acomplete(prompt)
        return str(response).strip().lower().replace(" ", "_")

    async def _persist_source_metadata(
        self,
        registry: UserDataRegistry,
        database: str,
        source: DataSource,
        source_id: str,
        queries: list[str],
    ) -> None:
        entry = {
            "source_id": source_id,
            "source_type": getattr(source, "source_type", "unknown"),
            "location": getattr(source, "location", ""),
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "queries": queries,
        }
        await registry.set_json(f"{database}:metadata:sources:{source_id}", entry)

    async def _write_data_entry(
        self,
        registry: UserDataRegistry,
        database: str,
        key: str,
        value: list[Any],
        source_id: str,
    ) -> None:
        metadata = {
            "date": datetime.now(timezone.utc).isoformat(),
            "agent": "import-agent-v1",
            "source_id": source_id,
        }
        entry = {"key": key, "value": value, "metadata": metadata}
        entry_id = str(uuid.uuid4())
        json_key = f"{database}:data:{entry_id}"
        await registry.set_json(json_key, entry)
        vector_text = f"{key}: {' '.join(str(v) for v in value)}"
        await registry.set_vector(json_key, vector_text, metadata)
