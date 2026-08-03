from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from blue_data.registry.data_registry import DataRegistry
from blue_data_kb_source.kb_source import KBSource


# ------------------------------------------------------------------ #
# Private builders                                                     #
# ------------------------------------------------------------------ #

def _build_json_source(props: dict) -> Any:
    """Build a JSONSource from backend config props."""
    if props.get("backend") == "file":
        from blue_data.source.json.file_json_source import FileJSONSource
        Path(props["path"]).parent.mkdir(parents=True, exist_ok=True)
        return FileJSONSource(props["path"])
    from blue_data.source.json.memory_json_source import MemoryJSONSource
    return MemoryJSONSource()


def _build_kb_source(kb_props: dict) -> Any:
    """Instantiate a concrete KBSource from flat backend config props.

    Expected keys: ``backend`` (``"memory"`` | ``"file"`` | ``"neo4j"``),
    plus backend-specific keys (``directory`` for file, ``uri`` / ``username``
    / ``password`` for neo4j).

    ``.properties`` stores ``connection`` so it survives a
    ``DataRegistry.register_source`` round-trip and can be read back by
    ``connect()``.
    """
    backend = kb_props.get("backend", "memory")
    extras = {k: v for k, v in kb_props.items() if k not in ("backend", "schema_path")}
    connection = {"backend": backend, **extras}
    stored_props: dict[str, Any] = {"connection": connection}

    if backend == "neo4j":
        from blue_data.source.graph.neo4j.neo4j_graph_source import NEO4JSource

        class _Neo4jKBSource(KBSource, NEO4JSource):  # type: ignore[misc]
            pass

        return _Neo4jKBSource(
            "kb",
            properties={"connection": {"protocol": "neo4j", **connection}},
        )

    if backend == "file":
        from blue_data.source.graph.file_graph_source import FileGraphSource

        class _FileKBSource(KBSource, FileGraphSource):  # type: ignore[misc]
            pass

        return _FileKBSource(
            "kb",
            directory=connection.get("directory", "."),
            properties=stored_props,
        )

    from blue_data.source.graph.memory_graph_source import MemoryGraphSource

    class _MemoryKBSource(KBSource, MemoryGraphSource):  # type: ignore[misc]
        pass

    return _MemoryKBSource("kb", properties=stored_props)


# ------------------------------------------------------------------ #
# Manager                                                              #
# ------------------------------------------------------------------ #

class UserDataManager:
    """Owns the DataRegistry and KBSource for one user database.

    Lifecycle::

        # new user — create registry + KB + seed schema
        mgr = UserDataManager("alice", registry_props)
        await mgr.initialize(kb_props)

        # existing user (persistent backend) — reconnect from stored record
        mgr = UserDataManager("alice", registry_props)
        mgr.connect()
    """

    def __init__(self, database: str, registry_props: dict) -> None:
        self._database = database
        self._registry_props = registry_props
        self._registry: DataRegistry | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def initialize(self, kb_props: dict) -> None:
        """Build a fresh DataRegistry + KBSource, register KB, and seed schema.

        ``kb_props`` keys: ``backend`` (required), plus backend-specific keys
        and optional ``schema_path``.
        """
        if not kb_props.get("backend"):
            raise ValueError("kb_props must include a 'backend' key")
        registry_store = _build_json_source(self._registry_props)
        self._registry = DataRegistry(store=registry_store)
        kb = _build_kb_source(kb_props)
        self._registry.register_source(kb)
        schema_path = kb_props.get("schema_path")
        if schema_path:
            await self.seed_schema(schema_path)

    def connect(self) -> None:
        """Build DataRegistry from stored props and reconnect the KBSource.

        Reads the ``"kb"`` source record from the registry's JSONSource and
        re-instantiates the KBSource from its stored connection properties.
        Also restores ``schema_path`` so ``reset()`` can reseed schema without
        needing the original ``kb_props``.
        """
        registry_store = _build_json_source(self._registry_props)
        self._registry = DataRegistry(store=registry_store)
        props = self._registry.get_source_properties("kb") or {}
        connection = props.get("connection", {})
        if not connection:
            raise ValueError(
                f"No 'kb' source found in registry for user {self._database!r}. "
                "Call create_user() to initialise."
            )
        kb = _build_kb_source(connection)
        self._registry.sources["kb"] = kb

    async def reset(self, schema_path: str | None = None) -> None:
        """Wipe KB data, remove non-KB registry sources, then reseed schema."""
        await self.clear_database()
        source_records = self._registry.list_records(record_type="source", scope="/")  # type: ignore[union-attr]
        for record in source_records:
            if record["name"] != "kb":
                self._registry.deregister(record)  # type: ignore[union-attr]
                self._registry.sources.pop(record["name"], None)  # type: ignore[union-attr]
        if schema_path:
            await self.seed_schema(schema_path)

    def destroy(self) -> None:
        """Delete all backing files for this user (file backends only).

        For non-file KB backends the caller is responsible for clearing
        the database namespace first (e.g. via ``reset()``).
        """
        # KB data file
        if self._registry is not None:
            props = self._registry.get_source_properties("kb") or {}
            connection = props.get("connection", {})
            if connection.get("backend") == "file":
                directory = connection.get("directory", ".")
                kb_file = Path(directory) / f"{self._database}.json"
                kb_file.unlink(missing_ok=True)

        # Per-user registry file
        if self._registry_props.get("backend") == "file":
            Path(self._registry_props["path"]).unlink(missing_ok=True)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _kb(self) -> KBSource:
        if self._registry is None:
            raise ValueError(
                "Registry not ready — call initialize() or connect() first."
            )
        kb = self._registry.get_source("kb")
        if kb is None:
            raise ValueError("No 'kb' source registered in registry.")
        return kb  # type: ignore[return-value]

    # ------------------------------------------------------------------ #
    # KB operations                                                        #
    # ------------------------------------------------------------------ #

    async def clear_database(self) -> None:
        """Wipe all nodes and edges from this user's database namespace."""
        self._kb().create_database(self._database, overwrite=True)

    async def seed_schema(self, schema_path: str) -> None:
        """Import schema from JSON into the KB and wire IS_SUBCLASS_OF edges."""
        schema_dict = json.loads(Path(schema_path).read_text())
        kb = self._kb()
        await kb.import_database_schema(self._database, {
            "entities": schema_dict["entities"],
            "relations": schema_dict["relations"],
        })
        for sc in schema_dict.get("subclasses", []):
            if sc["child_label"] not in ("CLASS", "RELATION"):
                continue
            if sc["parent_label"] not in ("CLASS", "RELATION"):
                continue
            child_results = await kb.search_schema(
                self._database, sc["child"], type_filter=sc["child_label"]
            )
            parent_results = await kb.search_schema(
                self._database, sc["parent"], type_filter=sc["parent_label"]
            )
            if child_results and parent_results:
                await kb.add_is_subclass_of(
                    self._database, child_results[0].id, parent_results[0].id
                )

    async def execute_query(
        self,
        query: str,
        top_k: int = 10,
    ) -> tuple[list[Any], dict[str, Any]]:
        results = await self._kb().search_data(self._database, query, k=top_k)
        return list(results), {}

    async def import_source(
        self,
        source: Any,
        queries: list[str] | None = None,
    ) -> None:
        kb = self._kb()
        location = getattr(source, "location", str(source))
        source_id = await kb.add_source(self._database, location)
        if queries:
            for query in queries:
                raw = await source.query(query)
                text = "\n".join(str(r) for r in raw)
                await kb.import_text(self._database, text, queries=[query], source_id=source_id)

    async def list_data(self) -> list[dict[str, Any]]:
        data = await self._kb().fetch_database_data(self._database, compact=True)
        if isinstance(data, list):
            return [item if isinstance(item, dict) else {"value": item} for item in data]
        return []

    async def list_metadata(self, source_id: str | None = None) -> list[dict[str, Any]]:
        nodes = self._kb().match_nodes(self._database, label="SOURCE")
        result: list[dict[str, Any]] = [
            {"id": n.get("id"), **n.get("properties", {})} for n in nodes
        ]
        if source_id is not None:
            result = [r for r in result if r.get("id") == source_id]
        return result

    async def store_data(
        self,
        text: str,
        source_id: str | None = None,
        queries: list[str] | None = None,
    ) -> None:
        await self._kb().import_text(self._database, text, queries=queries, source_id=source_id)
