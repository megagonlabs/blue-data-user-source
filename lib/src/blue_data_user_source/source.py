from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from blue_data.registry.data_registry import DataRegistry
from blue_data.source.source import DataSource

from blue_data_user_source.data.manager import (
    CLS_JSON_MEMORY,
    DEFAULT_DOC_SOURCE_PROPS,
    UserDataManager,
    _build_json_source,
    _enrich_props,
)
from blue_data_user_source.interaction.contact import ContactManager, ContactMethod
from blue_data_user_source.interaction.session import SessionManager
from blue_data_user_source.reasoning import UserQueryReasoner
from blue_data_user_source.types import QueryError, QueryResult

_DEFAULT_SCHEMA_PATH = str(Path(__file__).parent / "data" / "schema.json")
_DEFAULT_METADATA_SCHEMA_PATH = str(Path(__file__).parent / "data" / "metadata_schema.json")
_DEFAULT_CONTACT_SCHEMA_PATH = str(Path(__file__).parent / "data" / "contact_schema.json")


class UserSource(DataSource):
    """
    A multi-user data source for storing and querying personal user data on behalf of agents.

    Extends ``DataSource`` with the following mapping:
    - **database** → user name (e.g. ``"alice"``)
    - **collection** → registered source name in the per-user DataRegistry
      (``"kb"``, ``"metadata"``, ``"contacts"``, or any user-added source)

    Each user has an isolated ``DataRegistry`` that holds three built-in sources:

    - ``"kb"`` (``KBSource``) — knowledge graph of entities, facts, and property values
      extracted from text or imported files. Queried via natural language through
      ``execute_query`` / ``execute_query_nl``.
    - ``"metadata"`` (``JSONSource``) — structured metadata agents use when acting on
      the user's behalf: identity, preferences, policy (auto-approve/require-confirmation),
      credentials, skills, availability, and standing instructions. Seeded from
      ``data/metadata_schema.json`` on user creation so all keys are present (null) by
      default.
    - ``"contacts"`` (``JSONSource``) — preferred contact methods (email, Slack, SMS, …)
      used by agents to reach the user for clarification.

    Additional file-based sources can be registered at runtime via ``add_source``;
    they are stored in both the registry and the KB for provenance tracking.

    Props accepted by ``__init__``:

    - ``registry`` — JSONSource config for the outer DataRegistry's backing store
      (default: in-memory). File example::

          {"_class": "blue_data.source.json.file_json_source.FileJSONSource",
           "connection": {"protocol": "json/file", "path": "~/.udb/registry.json"}}

    - ``schema`` — path to the KB graph schema JSON (default: ``data/schema.json``).
      Stored as a property of the source record in the DataRegistry.
    - ``metadata_schema`` — path to the metadata schema JSON
      (default: ``data/metadata_schema.json``). Stored as a source property.
    - ``contact_schema`` — path to the contact schema JSON
      (default: ``data/contact_schema.json``). Stored as a source property.

    Usage::

        us = UserSource("user_source", {
            "registry": {
                "_class": "blue_data.source.json.file_json_source.FileJSONSource",
                "connection": {"protocol": "json/file", "path": "~/.udb/registry.json"},
            },
            "schema": "/path/to/schema.json",           # optional
            "metadata_schema": "/path/to/metadata.json" # optional
        })
        us.create_database("alice", properties={
            "registry": {
                "_class": "blue_data.source.json.file_json_source.FileJSONSource",
                "connection": {"protocol": "json/file", "path": "~/.udb/registries/alice.json"},
            },
            "kb_source": {
                "_class": "blue_data_kb_source.file_kb_source.FileKBSource",
                "connection": {"protocol": "kb/file", "directory": "~/.udb/sources/alice"},
            },
            "metadata_source": {
                "_class": "blue_data.source.json.file_json_source.FileJSONSource",
                "connection": {"protocol": "json/file", "path": "~/.udb/sources/alice/metadata.json"},
            },
            "contact_source": {
                "_class": "blue_data.source.json.file_json_source.FileJSONSource",
                "connection": {"protocol": "json/file", "path": "~/.udb/sources/alice/contacts.json"},
            },
        })
        results = us.execute_query("what are alice's skills?", database="alice")
        us.set_metadata("alice", "preferences.verbosity", "brief")
    """

    def __init__(self, name: str = "user_source", properties: dict | None = None) -> None:
        super().__init__(name, properties)
        # Build the outer DataRegistry backed by the JSONSource from properties["registry"]
        registry_json_props = self.properties.get("registry") or {
            "_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}
        }
        registry_store = _build_json_source(f"{name}_registry", registry_json_props)
        self._registry = DataRegistry(store=registry_store)
        self._managers: dict[str, UserDataManager] = {}

        # Register the source record in the outer DataRegistry, storing schema paths as properties.
        # On first run the record is created; on subsequent runs only explicitly provided values update it.
        existing = self._registry.get_source_record(name)
        cls = type(self)
        if existing is None:
            self._registry.register_record(
                name=name,
                type="source",
                scope="/",
                description=f"{name} user data source",
                properties={
                    **self.properties,
                    "_class": f"{cls.__module__}.{cls.__qualname__}",
                    "schema": self.properties.get("schema") or _DEFAULT_SCHEMA_PATH,
                    "metadata_schema": self.properties.get("metadata_schema") or _DEFAULT_METADATA_SCHEMA_PATH,
                    "contact_schema": self.properties.get("contact_schema") or _DEFAULT_CONTACT_SCHEMA_PATH,
                },
            )
        else:
            for key in ("connection", "registry", "schema", "metadata_schema", "contact_schema"):
                if self.properties.get(key):
                    self._registry.set_source_property(name, key, self.properties[key])

    # ------------------------------------------------------------------ #
    # DataSource: database = user                                          #
    # ------------------------------------------------------------------ #

    def fetch_databases(self) -> list[str]:
        return self.list_users()

    def fetch_database_metadata(self, database: str) -> dict:
        return self.get_user(database) or {}


    def create_database(self, database: str, properties: dict | None = None) -> dict:
        """Create a new user.  ``properties`` must contain:
        ``registry``, ``kb_source``, ``metadata_source``, ``contact_source``, ``session_source``.
        ``doc_source`` is optional (defaults to a dummy-embedding, in-memory vector backend).
        """
        p = properties or {}
        asyncio.run(self.create_user(
            database,
            registry_props=p["registry"],
            kb_source_props=p["kb_source"],
            metadata_source_props=p["metadata_source"],
            contact_source_props=p["contact_source"],
            session_source_props=p["session_source"],
            doc_source_props=p.get("doc_source"),
        ))
        return {}

    # ------------------------------------------------------------------ #
    # DataSource: collection = registered source in per-user DataRegistry  #
    # ------------------------------------------------------------------ #

    def fetch_database_collections(self, database: str) -> list[str]:
        records = self._get_manager(database)._registry.list_records(record_type="source", scope="/") or []
        return [r["name"] for r in records]

    def fetch_database_collection_metadata(self, database: str, collection: str) -> dict:
        return self._get_manager(database)._registry.get_source_properties(collection) or {}

    # ------------------------------------------------------------------ #
    # DataSource: query                                                    #
    # ------------------------------------------------------------------ #

    async def async_execute_query(
        self,
        query: str,
        database: str | None = None,
        optional_properties: dict | None = None,
    ) -> tuple[Any, str]:
        """Async version of execute_query for use from async contexts (e.g. FastAPI).

        Returns ``(results, session_id)`` — the reused or newly-created session
        this query landed in (see "session" in optional_properties).
        """
        return await self._run_query(query, database, optional_properties=optional_properties)

    def execute_query(
        self,
        query,
        database: str | None = None,
        collection: str | None = None,
        optional_properties: dict | None = None,
    ) -> tuple[list[dict], str]:
        """Returns ``(results, session_id)`` — see async_execute_query."""
        return asyncio.run(self._run_query(query, database, collection, optional_properties))

    def execute_query_nl(
        self,
        query: str,
        database: str | None = None,
        collection: str | None = None,
        schema: dict | None = None,    # noqa: ARG002 — UserSource uses its own reasoner
        llm_fn=None,                   # noqa: ARG002 — UserSource uses its own reasoner
        optional_properties: dict | None = None,
    ) -> tuple[list[dict], str]:
        """Returns ``(results, session_id)`` — see async_execute_query."""
        return asyncio.run(self._run_query(query, database, collection, optional_properties))

    # ------------------------------------------------------------------ #
    # DataSource: import                                                   #
    # ------------------------------------------------------------------ #

    def import_data(
        self,
        source: Any,
        collection: str,
        database: str = "default",
        entity: str | None = None,
        mode: str = "append",
        options: dict | None = None,
    ) -> dict:
        return asyncio.run(
            self._get_manager(database).import_data(source, collection, entity, mode, options)
        )

    # ------------------------------------------------------------------ #
    # User management (UserSource-specific API)                            #
    # ------------------------------------------------------------------ #

    async def create_user(
        self,
        name: str,
        registry_props: dict,
        kb_source_props: dict,
        metadata_source_props: dict,
        contact_source_props: dict,
        session_source_props: dict,
        doc_source_props: dict | None = None,
    ) -> None:
        """Build a fresh per-user registry + all sources, seed schema, register the user."""
        manager = UserDataManager(name, registry_props, doc_source_props=doc_source_props)
        await manager.build(
            schema_path=self._registry.get_source_property(self.name, "schema"),
            kb_source_props=kb_source_props,
            metadata_schema_path=self._registry.get_source_property(self.name, "metadata_schema"),
            metadata_source_props=metadata_source_props,
            contact_schema_path=self._registry.get_source_property(self.name, "contact_schema"),
            contact_source_props=contact_source_props,
            session_source_props=session_source_props,
        )
        # Register the user as a database entry with enriched registry props.
        # doc_source_props is persisted here (not in the per-user registry) because
        # it's read again by _get_manager on every reconnect, before build() would run.
        self._registry.register_source_database(
            self.name, name, properties={
                "registry": _enrich_props(registry_props, "json"),
                "doc_source": doc_source_props or DEFAULT_DOC_SOURCE_PROPS,
            }
        )
        self._managers[name] = manager

    def list_users(self) -> list[str]:
        return [r["name"] for r in (self._registry.list_source_databases(self.name) or [])]

    def get_user(self, name: str) -> dict | None:
        """Return the properties dict of the user's database record (contains ``registry`` key)."""
        record = self._registry.get_source_database(self.name, name)
        return record.get("properties") if record else None

    def remove_user(self, name: str) -> None:
        """Remove user from the registry; backing files are untouched."""
        self._registry.deregister_source_database(self.name, name)
        self._managers.pop(name, None)

    async def reset_user(self, name: str) -> None:
        await self._get_manager(name).reset(
            schema_path=self._registry.get_source_property(self.name, "schema"),
            metadata_schema_path=self._registry.get_source_property(self.name, "metadata_schema"),
            contact_schema_path=self._registry.get_source_property(self.name, "contact_schema"),
        )

    async def delete_user(self, name: str) -> None:
        manager = self._get_manager(name)
        manager.destroy()
        self.remove_user(name)

    # ------------------------------------------------------------------ #
    # Source management (UserSource-specific async API)                    #
    # ------------------------------------------------------------------ #

    async def add_source(
        self,
        source: Any,
        database: str,
        optional_properties: dict[str, object] | None = None,
    ) -> None:
        """Register a source in the user's KB and optionally ingest via queries."""
        props = optional_properties or {}
        queries: list[str] | None = None
        if "queries" in props:
            raw = props["queries"]
            if isinstance(raw, list):
                queries = [str(q) for q in raw]
        name = str(props["name"]) if "name" in props else None
        description = str(props["description"]) if "description" in props else None
        original = str(props["original"]) if "original" in props else None
        await self._get_manager(database).add_source(source, queries, name=name, description=description, original=original)

    def remove_source(self, database: str, source_name: str) -> None:
        """Remove a source from the user's DataRegistry without touching KB data."""
        self._get_manager(database).remove_source(source_name)

    # ------------------------------------------------------------------ #
    # Listing                                                              #
    # ------------------------------------------------------------------ #

    async def list_data(self, database: str) -> list[dict]:
        return await self._get_manager(database).list_data()

    async def list_sources(self, database: str, source_id: str | None = None) -> list[dict]:
        return await self._get_manager(database).list_sources(source_id)

    async def describe_data(self, database: str) -> str:
        entries = await self.list_data(database)
        return await UserQueryReasoner(source=self).synthesize_data_nl(entries)

    async def describe_sources(self, database: str, source_id: str | None = None) -> str:
        entries = await self.list_sources(database, source_id)
        return await UserQueryReasoner(source=self).synthesize_metadata_nl(entries)

    # ------------------------------------------------------------------ #
    # User metadata                                                        #
    # ------------------------------------------------------------------ #

    def get_metadata(self, database: str, key: str) -> Any:
        return self._get_manager(database).get_metadata(key)

    def set_metadata(self, database: str, key: str, value: Any) -> None:
        self._get_manager(database).set_metadata(key, value)

    def delete_metadata(self, database: str, key: str) -> None:
        self._get_manager(database).delete_metadata(key)

    def list_metadata(self, database: str) -> dict[str, Any]:
        return self._get_manager(database).list_metadata()

    # ------------------------------------------------------------------ #
    # Contact methods                                                      #
    # ------------------------------------------------------------------ #

    def _contact_manager(self, database: str) -> ContactManager:
        return ContactManager(database=database, data_manager=self._get_manager(database))

    async def add_contact_method(
        self,
        database: str,
        protocol: str,
        name: str,
        details: dict[str, Any],
        preference: int = 0,
    ) -> None:
        await self._contact_manager(database).create_contact_method(protocol, name, details, preference)

    async def get_contact_method(
        self, database: str, protocol: str, name: str
    ) -> ContactMethod | None:
        return await self._contact_manager(database).get_contact_method(protocol, name)

    async def update_contact_method(
        self, database: str, protocol: str, name: str, **updates: Any
    ) -> None:
        await self._contact_manager(database).update_contact_method(protocol, name, **updates)

    async def remove_contact_method(self, database: str, protocol: str, name: str) -> None:
        await self._contact_manager(database).delete_contact_method(protocol, name)

    # ------------------------------------------------------------------ #
    # Sessions                                                             #
    # ------------------------------------------------------------------ #

    def _session_manager(self, database: str) -> SessionManager:
        return SessionManager(database=database, data_manager=self._get_manager(database))

    async def create_session(self, database: str) -> str:
        return await self._session_manager(database).create_session()

    async def end_session(self, database: str, session_id: str) -> None:
        await self._session_manager(database).end_session(session_id)

    async def get_session(self, database: str, session_id: str) -> dict | None:
        return await self._session_manager(database).get_session(session_id)

    async def list_sessions(self, database: str) -> dict[str, Any]:
        return await self._session_manager(database).list_sessions()

    async def list_contact_methods(
        self, database: str, protocol: str | None = None
    ) -> list[ContactMethod]:
        return await self._contact_manager(database).list_contact_methods(protocol)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    async def _run_query(
        self,
        query: str,
        database: str | None = None,
        collection: str | None = None,  # noqa: ARG002 — routing to KB; collection unused
        optional_properties: dict | None = None,
    ) -> tuple[Any, str]:
        """Async query implementation shared by execute_query and execute_query_nl.

        Reuse-or-create session semantics: if "session" is present in
        optional_properties, this query is appended to that existing session
        (raises QueryError if it doesn't exist or has ended); otherwise a new
        single-query session is created automatically. Returns (results, session_id).
        """
        props = optional_properties or {}
        output_form = str(props.get("output_form", "json"))

        manager = self._get_manager(database)
        session_manager = self._session_manager(database)
        if "session" in props:
            session_id = str(props["session"])
            session = await session_manager.get_session(session_id)
            if session is None:
                raise QueryError(f"Unknown session {session_id!r}")
            if session.get("status") == "ended":
                raise QueryError(f"Session {session_id!r} has ended; cannot add a query to it.")
        else:
            session_id = await session_manager.create_session()
        query_id = await session_manager.create_query(session_id, query, output_form)

        reasoner = UserQueryReasoner(
            source=self, manager=manager, session_id=session_id, query_id=query_id
        )

        # Phase 1: contextualize then expand (sequential — expand uses the rewritten query)
        rewritten = await reasoner.contextualize_query(query)
        questions = await reasoner.expand_query(rewritten)
        questions.append(rewritten)

        on_tool_call = props.get("on_tool_call")
        on_tool_result = props.get("on_tool_result")

        # Phase 2: all queries in parallel (kb + session_content + external_documents)
        raw_results: list[tuple[list, dict]] = list(await asyncio.gather(*[
            manager.execute_query(
                q, on_tool_call=on_tool_call, on_tool_result=on_tool_result, session_id=session_id,
            )
            for q in questions
        ]))

        # Aggregate data + metadata across all sub-questions for a single quality pass
        all_data: list[Any] = [item for data, _ in raw_results for item in data]
        all_metadata: dict[str, Any] = {}
        for _, meta in raw_results:
            all_metadata.update(meta)

        # Phase 3: assess aggregate quality — metrics run in parallel
        metrics = await reasoner.assess_query_results(rewritten, all_data, all_metadata)

        # Phase 4: single interaction decision on aggregate results
        needs_interaction = await reasoner.assess_user_interaction(
            rewritten, all_data, all_metadata, metrics
        )

        results: list[QueryResult] = [
            QueryResult(query=q, results=data)
            for q, (data, _) in zip(questions, raw_results)
        ]

        if needs_interaction:
            augmented, _ = await reasoner.request_user_interaction(
                query, all_data, all_metadata, metrics
            )
            # Surface only the newly collected items (user response) as a separate result
            new_items = augmented[len(all_data):]
            if new_items:
                results.append(QueryResult(query=query, results=new_items))

        if output_form == "nl":
            return await reasoner.synthesize_results_nl(query, results), session_id
        return results, session_id

    def _get_manager(self, name: str) -> UserDataManager:
        if name not in self._managers:
            db_props = self.get_user(name)
            if db_props is None:
                raise QueryError(f"User not found: {name!r}")
            registry_props = db_props.get("registry") or {
                "_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}
            }
            doc_source_props = db_props.get("doc_source") or DEFAULT_DOC_SOURCE_PROPS
            manager = UserDataManager(name, registry_props, doc_source_props=doc_source_props)
            manager.connect()
            self._managers[name] = manager
        return self._managers[name]
