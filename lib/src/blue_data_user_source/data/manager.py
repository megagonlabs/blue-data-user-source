from __future__ import annotations

import json
from pathlib import Path
from typing import Any


from blue_data.registry.data_registry import DataRegistry
from blue_data_kb_source.kb_source import KBSource


# ------------------------------------------------------------------ #
# Private builders                                                     #
# ------------------------------------------------------------------ #

def _build_json_source(name: str, props: dict) -> Any:
    """Build a named JSONSource with registry-compatible properties."""
    if props.get("backend") == "file":
        from blue_data.source.json.file_json_source import FileJSONSource
        Path(props["path"]).parent.mkdir(parents=True, exist_ok=True)
        source = FileJSONSource(name, properties={"connection": {"path": props["path"]}})
    else:
        from blue_data.source.json.memory_json_source import MemoryJSONSource
        source = MemoryJSONSource()
    source.name = name
    source.properties = {"connection": props}
    return source


def _build_kb_source(name: str, props: dict) -> Any:
    """Instantiate a named KBSource from flat backend config props.

    Expected keys: ``backend`` (``"memory"`` | ``"file"`` | ``"neo4j"``),
    plus backend-specific keys (``directory`` for file, ``uri`` / ``username``
    / ``password`` for neo4j).

    ``.properties`` stores ``connection`` so it survives a
    ``DataRegistry.register_source`` round-trip.
    """
    backend = props.get("backend", "memory")
    extras = {k: v for k, v in props.items() if k not in ("backend", "schema_path")}
    connection = {"backend": backend, **extras}
    stored_props: dict[str, Any] = {"connection": connection}

    if backend == "neo4j":
        from blue_data.source.graph.neo4j.neo4j_graph_source import NEO4JSource

        class _Neo4jKBSource(KBSource, NEO4JSource):  # type: ignore[misc]
            pass

        return _Neo4jKBSource(
            name,
            properties={"connection": {"protocol": "neo4j", **connection}},
        )

    if backend == "file":
        from blue_data.source.graph.file_graph_source import FileGraphSource

        class _FileKBSource(KBSource, FileGraphSource):  # type: ignore[misc]
            pass

        return _FileKBSource(
            name,
            directory=connection.get("directory", "."),
            properties=stored_props,
        )

    from blue_data.source.graph.memory_graph_source import MemoryGraphSource

    class _MemoryKBSource(KBSource, MemoryGraphSource):  # type: ignore[misc]
        pass

    return _MemoryKBSource(name, properties=stored_props)


# ------------------------------------------------------------------ #
# Manager                                                              #
# ------------------------------------------------------------------ #

class UserDataManager:
    """Manages the DataRegistry and all user-specific sources for a user, including:
    - kb source (``"kb"``) — knowledge base data extracted from various sources,
    - metadata source — user metadata such as preferences and settings,
    - contact source — user contact information across multiple contact methods,
    - any additional sources added via imports.

    Lifecycle::

        # new user — build registry + all three sources + seed schema
        mgr = UserDataManager("alice", registry_props)
        await mgr.initialize(kb_source_props)

        # existing user (persistent backend) — registry loaded eagerly, sources lazy
        mgr = UserDataManager("alice", registry_props)
        mgr.connect()
    """

    def __init__(self, database: str, registry_props: dict) -> None:
        self._database = database
        self._registry_props = registry_props
        self._registry: DataRegistry | None = None
        self._kb_source: Any = None
        self._metadata_source: Any = None
        self._contact_source: Any = None

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def build(
        self,
        schema_path: str,
        kb_source_props: dict,
        metadata_schema_path: str | None,
        metadata_source_props: dict,
        contact_schema_path: str | None,
        contact_source_props: dict,
    ) -> None:
        """Build a fresh DataRegistry and all three sources."""
        registry_store = _build_json_source("registry", self._registry_props)
        self._registry = DataRegistry(store=registry_store)

        self._kb_source = _build_kb_source("kb", kb_source_props)
        self._registry.register_source(self._kb_source)
        await self.seed_kb_source_schema(schema_path)

        self._metadata_source = _build_json_source("metadata", metadata_source_props)
        self._registry.register_source(self._metadata_source)
        if metadata_schema_path:
            self.seed_metadata_schema(metadata_schema_path)

        self._contact_source = _build_json_source("contacts", contact_source_props)
        self._registry.register_source(self._contact_source)
        if contact_schema_path:
            self.seed_contact_schema(contact_schema_path)


    def connect(self) -> None:
        """Create a DataRegistry instance; 
        Sources within the registry will be connected lazily, 
        through data registry's source related methods.
        """
        registry_store = _build_json_source("registry", self._registry_props)
        self._registry = DataRegistry(store=registry_store)


    async def reset(
        self,
        schema_path: str | None = None,
        sources: set[str] | None = None,
    ) -> None:
        """Clear and optionally reseed selected sources.

        ``sources`` defaults to ``{"kb", "metadata", "contacts"}``.
        """
        if sources is None:
            sources = {"kb", "metadata", "contacts"}

        if "kb" in sources:
            await self.clear_kb()
            if schema_path:
                await self.seed_kb_source_schema(schema_path)

        if "metadata" in sources:
            self.clear_metadata()

        if "contacts" in sources:
            self.clear_contacts()

        # Deregister any additional imported sources from the registry
        source_records = self._registry.list_records(record_type="source", scope="/")
        for record in source_records:
            if record["name"] not in ("kb", "metadata", "contacts"):
                self._registry.deregister(record)

    def destroy(self) -> None:
        """Delete all backing files for this user, if file backends.

        For non-file KB backends the caller is responsible for clearing
        the database namespace first (e.g. via ``reset()``).
        """
  
        if self._registry is not None:
            # KB — stored with a directory-based path
            props = self._registry.get_source_properties("kb") or {}
            connection = props.get("connection", {})
            if connection.get("backend") == "file":
                (Path(connection.get("directory", ".")) / f"{self._database}.json").unlink(missing_ok=True)

            # Metadata and contact — stored with an explicit path
            for source_name in ("metadata", "contacts"):
                props = self._registry.get_source_properties(source_name) or {}
                connection = props.get("connection", {})
                if connection.get("backend") == "file" and connection.get("path"):
                    Path(connection["path"]).unlink(missing_ok=True)

        # Registry file
        if self._registry_props.get("backend") == "file":
            Path(self._registry_props["path"]).unlink(missing_ok=True)


    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _ensure_kb_source(self) -> KBSource:
        if self._registry is None:
            raise ValueError("Registry not ready — call initialize() or connect() first.")
        
        if self._kb_source is None:
            props = self._registry.get_source_properties("kb") or {}
            connection = props.get("connection", {})
            if not connection:
                raise ValueError(
                    f"No 'kb' source found in registry for user {self._database!r}."
                )
            self._kb_source = _build_kb_source("kb", connection)
            
        return self._kb_source 

    def _ensure_metadata_source(self) -> Any:
        if self._registry is None:
            raise ValueError("Registry not ready — call build() or connect() first.")
        
        if self._metadata_source is None:
            props = self._registry.get_source_properties("metadata") or {}
            connection = props.get("connection", {})
            if not connection:
                raise ValueError(f"No 'metadata' source in registry for user {self._database!r}.")
            self._metadata_source = _build_json_source("metadata", connection)
        return self._metadata_source

    def _ensure_contact_source(self) -> Any:
        if self._registry is None:
            raise ValueError("Registry not ready — call build() or connect() first.")
        if self._contact_source is None:
            props = self._registry.get_source_properties("contacts") or {}
            connection = props.get("connection", {})
            if not connection:
                raise ValueError(f"No 'contacts' source in registry for user {self._database!r}.")
            self._contact_source = _build_json_source("contacts", connection)
        return self._contact_source

    # ------------------------------------------------------------------ #
    # KB  Operations                                                     #
    # ------------------------------------------------------------------ #

    async def clear_kb(self) -> None:
        self._ensure_kb_source().create_database(self._database, overwrite=True)

    async def seed_kb_source_schema(self, schema_path: str) -> None:
        schema_dict = json.loads(Path(schema_path).read_text())
        kb = self._ensure_kb_source()
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
        on_tool_call=None,
        on_tool_result=None,
    ) -> tuple[list[Any], dict[str, Any]]:
        result, metadata = await self._ensure_kb_source().answer(
            self._database, query,
            include_metadata=True,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
        )
        data = result if isinstance(result, list) else ([{"answer": result}] if result else [])
        print(f"Query executed: {query}\nResults: {data}\nMetadata: {metadata}")
        return data, metadata

    async def import_data(
        self,
        source: Any,
        collection: str,
        entity: str | None = None,
        mode: str = "append",
        options: dict | None = None,
    ) -> dict:
        """Delegate to the KB source's import_data."""
        return self._ensure_kb_source().import_data(
            source, collection, self._database, entity, mode, options
        )

    async def add_source(
        self,
        source: Any,
        queries: list[str] | None = None,
        name: str | None = None,
        description: str | None = None,
        original: str | None = None,
    ) -> None:
        """Register a source location in the KB and the registry, then optionally ingest content."""
        kb = self._ensure_kb_source()
        location = getattr(source, "location", str(source))
        source_id = await kb.add_source(self._database, location, name=name, description=description, original=original)

        registry_name = name or location
        self._registry.register_record(
            name=registry_name,
            type="source",
            scope="/",
            description=description or "",
            properties={"connection": {"backend": "file", "path": location}, "source_id": source_id},
        )

        if queries:
            for query in queries:
                raw = await source.query(query)
                text = "\n".join(str(r) for r in raw)
                await kb.import_text(self._database, text, queries=[query], source_id=source_id)

    def remove_source(self, source_name: str) -> None:
        """Remove a source from the DataRegistry without touching KB data."""
        records = self._registry.list_records(record_type="source", scope="/") or []  # type: ignore[union-attr]
        for record in records:
            if record.get("name") == source_name:
                self._registry.deregister(record)  # type: ignore[union-attr]
                return

    async def list_data(self) -> list[dict[str, Any]]:
        data = await self._ensure_kb_source().fetch_database_data(self._database, compact=True)
        if isinstance(data, list):
            return [item if isinstance(item, dict) else {"value": item} for item in data]
        return []

    async def list_sources(self, source_id: str | None = None) -> list[dict[str, Any]]:
        """List registered data sources (SOURCE nodes in the KB)."""
        nodes = self._ensure_kb_source().match_nodes(self._database, label="SOURCE")
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
        await self._ensure_kb_source().import_text(
            self._database, text, queries=queries, source_id=source_id
        )

    # ------------------------------------------------------------------ #
    # Metadata operations                                                  #
    # ------------------------------------------------------------------ #

    def seed_metadata_schema(self, schema_path: str) -> None:
        """Initialize the metadata store with null values for all schema-defined keys.

        Skips keys that are already set, so calling this on an existing user is safe.
        Categories marked ``__open__: true`` (like credentials) are registered as empty
        dicts but have no fixed sub-keys to seed.
        """
        schema = json.loads(Path(schema_path).read_text())
        meta = self._ensure_metadata_source()
        for category, entries in schema.items():
            if meta.get(f"metadata.{category}") is None:
                meta.set(f"metadata.{category}", {})
            if entries.get("__open__"):
                continue
            for key, spec in entries.items():
                if key.startswith("__"):
                    continue
                dotted = f"metadata.{category}.{key}"
                if meta.get(dotted) is None:
                    meta.set(dotted, spec.get("default"))

    def clear_metadata(self) -> None:
        self._ensure_metadata_source().set("metadata", {})

    def get_metadata(self, key: str) -> Any:
        return self._ensure_metadata_source().get(f"metadata.{key}")

    def set_metadata(self, key: str, value: Any) -> None:
        self._ensure_metadata_source().set(f"metadata.{key}", value)

    def delete_metadata(self, key: str) -> None:
        self._ensure_metadata_source().delete(f"metadata.{key}")

    def list_metadata(self) -> dict[str, Any]:
        return self._ensure_metadata_source().get("metadata") or {}

    # ------------------------------------------------------------------ #
    # Contact source                                                       #
    # ------------------------------------------------------------------ #

    def seed_contact_schema(self, schema_path: str) -> None:
        """Initialize the contacts store with empty protocol buckets for all schema-defined protocols.

        Skips protocols already present. Named entries (work, personal, …) are user-defined
        and are not seeded — only the top-level protocol dict is ensured.
        """
        schema = json.loads(Path(schema_path).read_text())
        store = self._ensure_contact_source()
        for protocol in schema:
            if store.get(f"contacts.{protocol}") is None:
                store.set(f"contacts.{protocol}", {})

    def clear_contacts(self) -> None:
        self._ensure_contact_source().set("contacts", {})

    def get_contact_source(self) -> Any:
        return self._ensure_contact_source()

    def get_contacts(self) -> dict[str, Any]:
        return self._ensure_contact_source().get("contacts") or {}

    def get_contact(self, protocol: str, name: str) -> dict[str, Any] | None:
        return self._ensure_contact_source().get(f"contacts.{protocol}.{name}")

    def set_contact_field(self, protocol: str, name: str, field: str, value: Any) -> None:
        store = self._ensure_contact_source()
        if store.get(f"contacts.{protocol}.{name}") is None:
            store.set(f"contacts.{protocol}.{name}", {})
        store.set(f"contacts.{protocol}.{name}.{field}", value)

    def delete_contact(self, protocol: str, name: str) -> None:
        self._ensure_contact_source().delete(f"contacts.{protocol}.{name}")
