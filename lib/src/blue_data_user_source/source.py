from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from blue_data.source.source import DataSource
from blue_data_user_source.data.manager import UserDataManager, _build_json_source
from blue_data_user_source.interaction.contact import ContactManager, ContactMethod
from blue_data_user_source.reasoning import UserQueryReasoner
from blue_data_user_source.types import QueryError, QueryResult

_DEFAULT_SCHEMA_PATH = str(Path(__file__).parent / "data" / "schema.json")
_DEFAULT_METADATA_SCHEMA_PATH = str(Path(__file__).parent / "data" / "metadata_schema.json")


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

    - ``store`` — JSONSource config for the top-level user registry
      (default: in-memory). File example: ``{"backend": "file", "path": "~/.udb/db.json"}``.
    - ``schema`` — path to the KB graph schema JSON (default: ``data/schema.json``).
    - ``metadata_schema`` — path to the metadata schema JSON
      (default: ``data/metadata_schema.json``).

    Usage::

        us = UserSource({
            "store":           {"backend": "file", "path": "~/.udb/db.json"},
            "schema":          "/path/to/schema.json",          # optional
            "metadata_schema": "/path/to/metadata_schema.json", # optional
        })
        us.create_database("alice", properties={
            "registry":        {"backend": "file", "path": "~/.udb/registries/alice.json"},
            "kb_source":       {"backend": "file", "directory": "~/.udb/kb"},
            "metadata_source": {"backend": "file", "path": "~/.udb/sources/alice.metadata.json"},
            "contact_source":  {"backend": "file", "path": "~/.udb/sources/alice.contacts.json"},
        })
        results = us.execute_query("what are alice's skills?", database="alice")
        us.set_metadata("alice", "preferences.verbosity", "brief")
    """

    def __init__(self, props: dict) -> None:
        super().__init__(props.get("name", "user_source"), props)
        self._store = _build_json_source("store", props.get("store", {"backend": "memory"}))
        self._managers: dict[str, UserDataManager] = {}
        if self._store.get("users") is None:
            self._store.set("users", {})
        if props.get("schema") is not None:
            self._store.set("schema", props["schema"])
        elif self._store.get("schema") is None:
            self._store.set("schema", _DEFAULT_SCHEMA_PATH)
        if props.get("metadata_schema") is not None:
            self._store.set("metadata_schema", props["metadata_schema"])
        elif self._store.get("metadata_schema") is None:
            self._store.set("metadata_schema", _DEFAULT_METADATA_SCHEMA_PATH)

    # ------------------------------------------------------------------ #
    # DataSource: database = user                                          #
    # ------------------------------------------------------------------ #

    def fetch_databases(self) -> list[str]:
        return self.list_users()

    def fetch_database_metadata(self, database: str) -> dict:
        return self.get_user(database) or {}

    def create_database(self, database: str, properties: dict | None = None) -> dict:
        """Create a new user.  ``properties`` must contain four keys:
        ``registry``, ``kb_source``, ``metadata_source``, ``contact_source``.
        """
        p = properties or {}
        asyncio.run(self.create_user(
            database,
            registry_props=p["registry"],
            kb_source_props=p["kb_source"],
            metadata_source_props=p["metadata_source"],
            contact_source_props=p["contact_source"],
        ))
        return {}

    # ------------------------------------------------------------------ #
    # DataSource: collection = registered source in per-user DataRegistry  #
    # ------------------------------------------------------------------ #

    def fetch_database_collections(self, database: str) -> list[str]:
        manager = self._get_manager(database)
        records = manager._registry.list_records(record_type="source", scope="/") or []
        return [r["name"] for r in records]

    def fetch_database_collection_metadata(self, database: str, collection: str) -> dict:
        manager = self._get_manager(database)
        return manager._registry.get_source_properties(collection) or {}

    # ------------------------------------------------------------------ #
    # DataSource: query                                                    #
    # ------------------------------------------------------------------ #

    def execute_query(
        self,
        query,
        database: str | None = None,
        collection: str | None = None,
        optional_properties: dict | None = None,
    ) -> list[dict]:
        return asyncio.run(self._run_query(query, database, collection, optional_properties))

    def execute_query_nl(
        self,
        query: str,
        database: str | None = None,
        collection: str | None = None,
        schema: dict | None = None,    # noqa: ARG002 — UserSource uses its own reasoner
        llm_fn=None,                   # noqa: ARG002 — UserSource uses its own reasoner
        optional_properties: dict | None = None,
    ) -> list[dict]:
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

    def add_user(self, name: str, registry_props: dict) -> None:
        """Wire up an existing registry that already has all three sources registered."""
        manager = UserDataManager(name, registry_props)
        manager.connect()
        self._store.set(f"users.{name}", {"registry": registry_props})
        self._managers[name] = manager

    async def create_user(
        self,
        name: str,
        registry_props: dict,
        kb_source_props: dict,
        metadata_source_props: dict,
        contact_source_props: dict,
    ) -> None:
        """Build a fresh registry + all three sources, seed schema, and register the user."""
        schema_path = self._store.get("schema")
        metadata_schema_path = self._store.get("metadata_schema")
        manager = UserDataManager(name, registry_props)
        await manager.build(schema_path, kb_source_props, metadata_schema_path, metadata_source_props, contact_source_props)
        self._store.set(f"users.{name}", {"registry": registry_props})
        self._managers[name] = manager

    def list_users(self) -> list[str]:
        return list((self._store.get("users") or {}).keys())

    def get_user(self, name: str) -> dict | None:
        return self._store.get(f"users.{name}")

    def remove_user(self, name: str) -> None:
        """Remove user from the store; backing files are untouched."""
        self._store.delete(f"users.{name}")
        self._managers.pop(name, None)

    async def reset_user(self, name: str) -> None:
        await self._get_manager(name).reset(self._store.get("schema"))

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
        await self._get_manager(database).add_source(source, queries, name=name, description=description)

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
        name: str,
        protocol: str,
        details: dict[str, Any],
        preference: int = 0,
    ) -> None:
        await self._contact_manager(database).create_contact_method(name, protocol, details, preference)

    async def get_contact_method(self, database: str, name: str) -> ContactMethod | None:
        return await self._contact_manager(database).get_contact_method(name)

    async def update_contact_method(self, database: str, name: str, **updates: Any) -> None:
        await self._contact_manager(database).update_contact_method(name, **updates)

    async def remove_contact_method(self, database: str, name: str) -> None:
        await self._contact_manager(database).delete_contact_method(name)

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
    ) -> list[dict]:
        """Async query implementation shared by execute_query and execute_query_nl."""
        props = optional_properties or {}
        session_id = str(props["session"]) if "session" in props else None
        output_form = str(props.get("output_form", "json"))

        manager = self._get_manager(database)
        reasoner = UserQueryReasoner(source=self, manager=manager, session_id=session_id)

        rewritten = await reasoner.contextualize_query(query)
        questions = await reasoner.expand_query(rewritten)
        questions.append(rewritten)

        on_tool_call = props.get("on_tool_call")
        on_tool_result = props.get("on_tool_result")

        results: list[QueryResult] = []
        for question in questions:
            data, metadata = await manager.execute_query(
                question, on_tool_call=on_tool_call, on_tool_result=on_tool_result
            )
            metrics = await reasoner.assess_query_results(question, data, metadata)
            needs_interaction = await reasoner.assess_user_verification(
                question, data, metadata, metrics
            )
            if needs_interaction:
                data, metadata = await reasoner.request_user_clarification(
                    question, data, metadata, metrics
                )
            results.append(QueryResult(query=question, results=data))

        if output_form == "nl":
            return await reasoner.synthesize_results_nl(query, results)
        return results

    def _get_manager(self, name: str) -> UserDataManager:
        if name not in self._managers:
            entry = self._store.get(f"users.{name}")
            if entry is None:
                raise QueryError(f"User not found: {name!r}")
            registry_props = entry.get("registry", {"backend": "memory"})
            manager = UserDataManager(name, registry_props)
            manager.connect()
            self._managers[name] = manager
        return self._managers[name]
