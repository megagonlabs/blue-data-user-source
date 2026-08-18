from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from blue_data.registry.data_registry import DataRegistry
from blue_data.source.source import DataSource
from blue_data_kb_source.kb_source import KBSource


# ------------------------------------------------------------------ #
# Class paths for DataSource.instantiate                               #
# ------------------------------------------------------------------ #

# Canonical class paths — import these in CLI / tests instead of hard-coding strings.
CLS_JSON_MEMORY = "blue_data.source.json.memory_json_source.MemoryJSONSource"
CLS_JSON_FILE   = "blue_data.source.json.file_json_source.FileJSONSource"
CLS_JSON_REDIS  = "blue_data.source.json.redis.redis_json_source.RedisJSONSource"
CLS_KB_MEMORY   = "blue_data_kb_source.memory_kb_source.MemoryKBSource"
CLS_KB_FILE     = "blue_data_kb_source.file_kb_source.FileKBSource"
CLS_KB_NEO4J    = "blue_data_kb_source.neo4j.neo4j_kb_source.NEO4JKBSource"

# Legacy mapping — kept for backward compatibility when reading stored configs
# that pre-date the _class / connection property format.
_KB_BACKENDS: dict[str, str] = {
    "memory": CLS_KB_MEMORY,
    "file":   CLS_KB_FILE,
    "neo4j":  CLS_KB_NEO4J,
}
_JSON_BACKENDS: dict[str, str] = {
    "memory": CLS_JSON_MEMORY,
    "file":   CLS_JSON_FILE,
}


def _enrich_props(props: dict, kind: str) -> dict:
    """Normalise *props* to ``{"_class": "...", "connection": {...}}``.

    Pass-through when *props* already has ``_class``.  Falls back to the
    legacy ``{"backend": "..."}`` shape for backward compatibility when
    reading old stored configs.
    """
    if "_class" in props:
        return props
    backend = props.get("backend", "memory")
    backends = _KB_BACKENDS if kind == "kb" else _JSON_BACKENDS
    cls = backends.get(backend)
    if cls is None:
        raise ValueError(f"Unknown {kind} backend: {backend!r}")
    return {"_class": cls, "connection": props}


def _build_json_source(name: str, props: dict) -> Any:
    """Bootstrap a JSONSource using DataSource.instantiate."""
    enriched = _enrich_props(props, "json")
    conn = enriched.get("connection", {})
    if conn.get("protocol", "").startswith("json/file") and "path" in conn:
        Path(conn["path"]).parent.mkdir(parents=True, exist_ok=True)
    # Pass through all top-level keys (e.g. "namespace" for Redis) alongside connection
    extra = {k: v for k, v in enriched.items() if k not in ("_class", "connection")}
    return DataSource.instantiate(enriched["_class"], name, properties={"connection": conn, **extra})


# ------------------------------------------------------------------ #
# Manager                                                              #
# ------------------------------------------------------------------ #

class UserDataManager:
    """Manages the per-user DataRegistry and all user-specific sources.

    Sources in the per-user registry:
    - ``"kb"``       (KBSource) — knowledge graph.
    - ``"metadata"`` (JSONSource) — user metadata / preferences.
    - ``"contacts"`` (JSONSource) — contact methods.
    - Additional sources added at runtime via :meth:`add_source`.

    All source instantiation goes through ``DataSource.instantiate`` using
    the ``_class`` stored in each source's registry record.  :meth:`connect`
    reconstructs sources lazily via ``DataRegistry.connect_source``.

    Lifecycle::

        # new user
        mgr = UserDataManager("alice", registry_props)
        await mgr.build(schema_path, kb_source_props, ...)

        # existing user (persistent backend)
        mgr = UserDataManager("alice", registry_props)
        mgr.connect()
    """

    def __init__(self, database: str, registry_props: dict) -> None:
        self._database = database
        self._registry_props = registry_props
        self._registry: DataRegistry | None = None
        # Optional overrides — set directly by callers (e.g. test mocks)
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
        """Create the per-user DataRegistry, instantiate + register all sources, seed schemas."""
        registry_store = _build_json_source("registry", self._registry_props)
        self._registry = DataRegistry(store=registry_store)

        # KB source
        kb_enriched = _enrich_props(kb_source_props, "kb")
        kb_source = DataSource.instantiate(
            kb_enriched["_class"], "kb",
            properties={"connection": kb_enriched.get("connection", {})},
        )
        self._registry.register_source(kb_source)
        await self.seed_kb_source_schema(schema_path)

        # Metadata source
        meta_enriched = _enrich_props(metadata_source_props, "json")
        meta_conn = meta_enriched.get("connection", {})
        if "path" in meta_conn:
            Path(meta_conn["path"]).parent.mkdir(parents=True, exist_ok=True)
        meta_source = DataSource.instantiate(
            meta_enriched["_class"], "metadata", properties={"connection": meta_conn},
        )
        self._registry.register_source(meta_source)
        if metadata_schema_path:
            self.seed_metadata_schema(metadata_schema_path)

        # Contacts source
        cont_enriched = _enrich_props(contact_source_props, "json")
        cont_conn = cont_enriched.get("connection", {})
        if "path" in cont_conn:
            Path(cont_conn["path"]).parent.mkdir(parents=True, exist_ok=True)
        cont_source = DataSource.instantiate(
            cont_enriched["_class"], "contacts", properties={"connection": cont_conn},
        )
        self._registry.register_source(cont_source)
        if contact_schema_path:
            self.seed_contact_schema(contact_schema_path)

    def connect(self) -> None:
        """Load the per-user DataRegistry from its existing store; sources are lazy via connect_source."""
        registry_store = _build_json_source("registry", self._registry_props)
        self._registry = DataRegistry(store=registry_store)

    async def reset(
        self,
        schema_path: str | None = None,
        metadata_schema_path: str | None = None,
        contact_schema_path: str | None = None,
        sources: set[str] | None = None,
    ) -> None:
        """Clear and reseed selected sources back to schema defaults."""
        if sources is None:
            sources = {"kb", "metadata", "contacts"}

        if "kb" in sources:
            await self.clear_kb()
            if schema_path:
                await self.seed_kb_source_schema(schema_path)

        if "metadata" in sources:
            self.clear_metadata()
            if metadata_schema_path:
                self.seed_metadata_schema(metadata_schema_path)

        if "contacts" in sources:
            self.clear_contacts()
            if contact_schema_path:
                self.seed_contact_schema(contact_schema_path)

        # Deregister any additional imported sources from the registry
        source_records = self._registry.list_records(record_type="source", scope="/")
        for record in source_records:
            if record["name"] not in ("kb", "metadata", "contacts"):
                self._registry.deregister(record)

    def destroy(self) -> None:
        """Delete all backing files for this user's sources, if file backends."""
        if self._registry is not None:
            # KB — file backend stores {database}.json inside the directory
            kb_props = self._registry.get_source_properties("kb") or {}
            kb_conn = kb_props.get("connection", {})
            if "directory" in kb_conn:
                user_dir = Path(kb_conn["directory"])
                (user_dir / f"{self._database}.json").unlink(missing_ok=True)
                with contextlib.suppress(OSError):
                    user_dir.rmdir()

            # Metadata and contacts — file path
            for src_name in ("metadata", "contacts"):
                props = self._registry.get_source_properties(src_name) or {}
                conn = props.get("connection", {})
                if "path" in conn:
                    Path(conn["path"]).unlink(missing_ok=True)

        # Per-user registry file
        reg_conn = self._registry_props.get("connection", self._registry_props)
        if "path" in reg_conn:
            Path(reg_conn["path"]).unlink(missing_ok=True)

    # ------------------------------------------------------------------ #
    # Internal source access (via DataRegistry.connect_source)            #
    # ------------------------------------------------------------------ #

    def _ensure_kb_source(self) -> KBSource:
        if self._kb_source is not None:
            return self._kb_source
        if self._registry is None:
            raise ValueError("Registry not ready — call build() or connect() first.")
        source = self._registry.connect_source("kb")
        if source is None:
            raise ValueError(f"No 'kb' source in registry for user {self._database!r}.")
        self._kb_source = source
        return source

    def _ensure_metadata_source(self) -> Any:
        if self._metadata_source is not None:
            return self._metadata_source
        if self._registry is None:
            raise ValueError("Registry not ready — call build() or connect() first.")
        source = self._registry.connect_source("metadata")
        if source is None:
            raise ValueError(f"No 'metadata' source in registry for user {self._database!r}.")
        self._metadata_source = source
        return source

    def _ensure_contact_source(self) -> Any:
        if self._contact_source is not None:
            return self._contact_source
        if self._registry is None:
            raise ValueError("Registry not ready — call build() or connect() first.")
        source = self._registry.connect_source("contacts")
        if source is None:
            raise ValueError(f"No 'contacts' source in registry for user {self._database!r}.")
        self._contact_source = source
        return source

    # ------------------------------------------------------------------ #
    # KB operations                                                        #
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
        print(f"Query executed: {query}")
        return data, metadata

    async def import_data(
        self,
        source: Any,
        collection: str,
        entity: str | None = None,
        mode: str = "append",
        options: dict | None = None,
    ) -> dict:
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
        """Register a source in the KB and registry, then optionally ingest content."""
        kb = self._ensure_kb_source()
        location = getattr(source, "location", str(source))
        source_id = await kb.add_source(
            self._database, location, name=name, description=description, original=original
        )

        registry_name = name or location
        src_cls = type(source)
        src_conn = getattr(source, "properties", {}).get("connection") or {"path": str(location)}
        self._registry.register_record(
            name=registry_name,
            type="source",
            scope="/",
            description=description or "",
            properties={
                "_class": f"{src_cls.__module__}.{src_cls.__qualname__}",
                "connection": src_conn,
                "source_id": source_id,
            },
        )

        if queries:
            for query in queries:
                raw = await source.query(query)
                text = "\n".join(str(r) for r in raw)
                await kb.import_text(self._database, text, queries=[query], source_id=source_id)

    def remove_source(self, source_name: str) -> None:
        """Remove a source from the DataRegistry without touching KB data."""
        records = self._registry.list_records(record_type="source", scope="/") or []
        for record in records:
            if record.get("name") == source_name:
                self._registry.deregister(record)
                return

    async def list_data(self) -> list[dict[str, Any]]:
        data = await self._ensure_kb_source().fetch_database_data(self._database, compact=True)
        if isinstance(data, list):
            return [item if isinstance(item, dict) else {"value": item} for item in data]
        return []

    async def list_sources(self, source_id: str | None = None) -> list[dict[str, Any]]:
        """List SOURCE nodes in the KB graph."""
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
    # Contact operations                                                   #
    # ------------------------------------------------------------------ #

    def seed_contact_schema(self, schema_path: str) -> None:
        """Initialize the contacts store with empty protocol buckets.

        Skips protocols already present.
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
