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


def _build_kb_source(kb_source_props: dict) -> Any:
    """Instantiate a concrete KBSource from flat backend config props.

    Expected keys: ``backend`` (``"memory"`` | ``"file"`` | ``"neo4j"``),
    plus backend-specific keys (``directory`` for file, ``uri`` / ``username``
    / ``password`` for neo4j).

    ``.properties`` stores ``connection`` so it survives a
    ``DataRegistry.register_source`` round-trip and can be read back by
    ``_ensure_kb_source()``.
    """
    backend = kb_source_props.get("backend", "memory")
    extras = {k: v for k, v in kb_source_props.items() if k not in ("backend", "schema_path")}
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
        metadata_source_props: dict,
        contact_source_props: dict
    ) -> None:
        
        """
        Build a fresh DataRegistry and all three sources.
        """

        # Create a new registry for user.
        registry_store = _build_json_source(self._registry_props)
        self._registry = DataRegistry(store=registry_store)

        # KB source 
        kb_source = _build_kb_source(kb_source_props)
        self._kb_source = kb_source
        self._registry.register_source(kb_source)
        # Seed the KB source schema if provided
        await self.seed_kb_source_schema(schema_path)

        # Metadata source
        metadata_source = _build_json_source(metadata_source_props) 
        self._metadata_source = metadata_source
        self._registry.register_source(metadata_source)

        # Contact source
        contact_source = _build_json_source(contact_source_props)
        self._contact_source = contact_source
        self._registry.register_source(contact_source)

        

    def connect(self) -> None:
        """Create a DataRegistry instance; 
        Sources will be connected lazily, through data registry's methods.
        """
        registry_store = _build_json_source(self._registry_props)
        self._registry = DataRegistry(store=registry_store)


    async def reset(
        self,
        schema_path: str | None = None,
        sources: set[str] | None = None,
    ) -> None:
        """Clear and optionally reseed selected sources.

        ``sources`` defaults to ``{"kb", "metadata", "contact"}``.
        """
        if sources is None:
            sources = {"kb", "metadata", "contact"}

        if "kb" in sources:
            await self.clear_kb()
            if schema_path:
                await self.seed_kb_schema(schema_path)

        if "metadata" in sources:
            await self.clear_metadata

        if "contact" in sources:
            await self.clear_contacts()

        # All other sources, just remove them from the registry 
        source_records = self._registry.list_records(record_type="source", scope="/")  
        for record in source_records:
            if record["name"] not in ("kb", "metadata", "contact"):
                self._registry.deregister(record) 

    def destroy(self) -> None:
        """Delete all backing files for this user, if file backends.

        For non-file KB backends the caller is responsible for clearing
        the database namespace first (e.g. via ``reset()``).
        """
  
        if self._registry is not None:
            # KB data file 
            props = self._registry.get_source_properties("kb") or {}
            connection = props.get("connection", {})
            if connection.get("backend") == "file":
                kb_file = Path(connection.get("directory", ".")) / f"{self._database}.json"
                kb_file.unlink(missing_ok=True)

            # Metadata data file    
            props = self._registry.get_source_properties("metadata") or {}
            connection = props.get("connection", {})
            if connection.get("backend") == "file":
                metadata_file = Path(connection.get("directory", ".")) / f"{self._database}.metadata.json"
                metadata_file.unlink(missing_ok=True)

            # Contact data file
            props = self._registry.get_source_properties("contacts") or {}
            connection = props.get("connection", {})
            if connection.get("backend") == "file":
                contacts_file = Path(connection.get("directory", ".")) / f"{self._database}.contacts.json"
                contacts_file.unlink(missing_ok=True)

        # Registry file
        if self._registry_props.get("backend") == "file":
            p = Path(self._registry_props["path"])
            p.unlink(missing_ok=True)


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
            self._kb_source = _build_kb_source(connection)
            
        return self._kb_source 

    def _ensure_metadata_source(self) -> Any:
        if self._registry is None:
            raise ValueError("Registry not ready — call initialize() or connect() first.")
        
        if self._metadata_source is None:
            props = self._registry.get_source_properties("metadata") or {}
            connection = props.get("connection", {})
            if not connection:
                raise ValueError(
                    f"No 'metadata' source found in registry for user {self._database!r}."
                )
            self._metadata_source = _build_json_source(connection)
        return self._metadata_source

    def _ensure_contact_source(self) -> Any:
        if self._registry is None:
            raise ValueError("Registry not ready — call initialize() or connect() first.")

        if self._contact_source is None:
            props = self._registry.get_source_properties("contacts") or {}
            connection = props.get("connection", {})
            if not connection:
                raise ValueError(
                    f"No 'contacts' source found in registry for user {self._database!r}."
                )
            self._contact_source = _build_json_source(connection)
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
        top_k: int = 10,
    ) -> tuple[list[Any], dict[str, Any]]:
        results = await self._ensure_kb_source().search_data(self._database, query, k=top_k)
        return list(results), {}

    async def import_source(
        self,
        source: Any,
        queries: list[str] | None = None,
    ) -> None:
        kb = self._ensure_kb_source()
        location = getattr(source, "location", str(source))
        source_id = await kb.add_source(self._database, location)
        if queries:
            for query in queries:
                raw = await source.query(query)
                text = "\n".join(str(r) for r in raw)
                await kb.import_text(self._database, text, queries=[query], source_id=source_id)

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

    async def clear_metadata(self) -> None:
        await self._ensure_metadata_source().set("metadata", {})

    async def get_metadata(self, key: str) -> Any:
        return await self._ensure_metadata_source().get(f"metadata.{key}")

    async def set_metadata(self, key: str, value: Any) -> None:
        await self._ensure_metadata_source().set(f"metadata.{key}", value)

    async def delete_metadata(self, key: str) -> None:
        await  self._ensure_metadata_source().delete(f"metadata.{key}")

    async def list_metadata(self) -> dict[str, Any]:
        return await self._ensure_metadata_source().get("metadata") or {}

    # ------------------------------------------------------------------ #
    # Contact source                                                       #
    # ------------------------------------------------------------------ #

    async def clear_contacts(self) -> None:
        await self._ensure_contact_source().set("contacts", {})

    async def get_contact_source(self) -> Any:
        return await self._ensure_contact_source()
