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

    def __init__(self, store_factory: StoreFactory | None, schema_path: str | None = None) -> None:
        self._store_factory = store_factory
        self._registries: dict[str, UserDataRegistry] = {}
        self._schema_reference = open(schema_path).read() if schema_path else ""

    async def create_user(self, name: str) -> None:
        """Initialize JSON and vector stores for a new user database."""
        if self._store_factory is None:
            raise ValueError("No store_factory configured. Pass 'store_factory' in UserSource properties.")
        json_store, vector_store = self._store_factory(name)
        registry = UserDataRegistry(json_store, vector_store)

        await registry.register_source(f"{name}:json", json_store)
        await registry.register_source(f"{name}:vector", vector_store)

        self._registries[name] = registry

    async def _ensure_loaded(self, database: str) -> UserDataRegistry:
        if database not in self._registries:
            await self.create_user(database)
        return self._registries[database]

    async def execute_query(self, query: str, database: str) -> tuple[list[Any], dict[str, Any]]:
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
                    schema = await self._llm_extract_schema(query)
                    extracted, sources = await self._llm_extract_data(query, schema, raw)
                except Exception as exc:
                    raise ImportError(f"Query over source failed: {exc}") from exc
                for entry_key, entry_values in extracted.items():
                    await self._write_data_entry(
                        registry, database, entry_key,
                        self._normalize_to_list(entry_values), source_id,
                        source_text=sources.get(entry_key),
                    )
            await self._persist_source_metadata(registry, database, source, source_id, queries)

    async def list_data(self, database: str, key: str | None = None) -> list[dict[str, Any]]:
        """Return data entries for the database, optionally filtered by attribute key name."""
        registry = await self._ensure_loaded(database)
        prefix = f"{database}:data:"
        keys = await registry.json_keys(prefix)
        entries: list[dict[str, Any]] = []
        for k in keys:
            entry = await registry.get_json(k)
            if entry is None:
                continue
            if key is None or entry.get("key") == key:
                entries.append(entry)
        return entries

    async def list_metadata(self, database: str, source_id: str | None = None) -> list[dict[str, Any]]:
        """Return source metadata entries for the database, optionally filtered by source_id."""
        registry = await self._ensure_loaded(database)
        prefix = f"{database}:metadata:sources:"
        keys = await registry.json_keys(prefix)
        entries: list[dict[str, Any]] = []
        for k in keys:
            entry = await registry.get_json(k)
            if entry is None:
                continue
            if source_id is None or entry.get("source_id") == source_id:
                entries.append(entry)
        return entries

    async def store_data(
        self,
        database: str,
        key: str,
        value: Any,
        source_id: str = "interaction",
        source_text: str | None = None,
    ) -> None:
        """Write a data entry to the user DB JSON store."""
        registry = await self._ensure_loaded(database)
        await self._write_data_entry(registry, database, key, self._normalize_to_list(value), source_id, source_text=source_text)

    @staticmethod
    def _normalize_to_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        return [value]

    async def _llm_extract_data(
        self, query: str, schema: list[str], raw_content: list[Any]
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Extract query-relevant data and the source text segment for each extracted value."""
        llm = Settings.llm
        content_str = "\n".join(str(item) for item in raw_content)
        prompt = (
            f"Extract information relevant to the following query from the content below.\n"
            f"Query: {query}\n\n"
            f"Schema: {schema}\n\n"
            f"Content:\n{content_str}\n\n"
            "Return a JSON object where each key is a matched attribute name from the schema and each value is an object with:\n"
            "  \"values\": a JSON array of the extracted values\n"
            "  \"source\": the verbatim excerpt from the content that the values were extracted from\n"
            "If no matching value is extracted, return an empty JSON object.\n"
            "Be as specific as possible and do not include irrelevant information."
        )
        response = await llm.acomplete(prompt)
        result_str = str(response).strip()
        try:
            parsed = json.loads(result_str)
        except (json.JSONDecodeError, ValueError):
            return {}, {}
        values: dict[str, Any] = {}
        sources: dict[str, str] = {}
        for key, entry in parsed.items():
            if isinstance(entry, dict) and "values" in entry:
                values[key] = entry["values"]
                if "source" in entry:
                    sources[key] = entry["source"]
            else:
                values[key] = entry
        return values, sources

    async def _llm_extract_schema(self, query: str) -> list[str]:
        """Derive a schema 'NodeType.attribute_name' path from a query."""
        llm = Settings.llm
        prompt = (
            "Map the following query to the most appropriate schema entries in the user data schema below.\n"
            "Return the result as a list of entries, as below:\n"
            "If matched schema entry is a NODE ATTRIBUTE, return matching NODE key value and NODE ATTRIBUTE name in the format 'node_key_value.attribute_name', e.g. alice.gender where alice is PERSON.first_name and PERSON.first_name is a key of PERSON node, gender is PERSON.gender attribute\n"
            "If matched schema entry is a RELATION, return matching source NODE key value and RELATION name in the format 'source_node_key_value.relation_name', e.g. alice.IS_FRIEND where alice is PERSON.first_name, IS_FRIEND is PERSON.IS_FRIEND.PERSON relationship"
            "If matched schema entry is a RELATION ATTRIBUTE, return matching source NODE key value and RELATION name and target NODE key and RELATION ATTRIBUTE name in the format 'source_node_key_value.relation_name.target_node_key_value.relation_attribute_name', e.g. alice.IS_FRIEND.bob.start_date where alice is PERSON.first_name, IS_FRIEND is PERSON.IS_FRIEND.PERSON relationship, bob is PERSON.first_name, start_date is PERSON.IS_FRIEND.PERSON attribute"
            "If no exact attribute matches, extend using the same conventions in the schema"
            f"SCHEMA:\n{self._schema_reference}\n"
            f"Query: {query}\n\n"
            "Return result JSON and nothing else."
        )
        response = await llm.acomplete(prompt)
        result_str = str(response).strip()
        try:
            parsed = json.loads(result_str)
        except (json.JSONDecodeError, ValueError):
            return []
        return parsed

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
        source_text: str | None = None,
    ) -> None:
        for item in value:
            metadata: dict[str, Any] = {
                "date": datetime.now(timezone.utc).isoformat(),
                "agent": "import-agent-v1",
                "source_id": source_id,
            }
            if source_text is not None:
                metadata["source_text"] = source_text
            entry = {"key": key, "value": item, "metadata": metadata}
            entry_id = str(uuid.uuid4())
            json_key = f"{database}:data:{entry_id}"
            await registry.set_json(json_key, entry)
            vector_text = f"{key}: {item}"
            await registry.set_vector(json_key, vector_text, metadata)
