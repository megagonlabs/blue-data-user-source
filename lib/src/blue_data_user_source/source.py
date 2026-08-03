from __future__ import annotations

from pathlib import Path
from typing import Any

from blue_data_user_source.data.manager import UserDataManager, _build_json_source

from blue_data_user_source.reasoning import UserQueryReasoner
from blue_data_user_source.types import QueryError, QueryResult

_DEFAULT_SCHEMA_PATH = str(Path(__file__).parent / "data" / "schema.json")


class UserSource:
    """
    A multi-user knowledge base source to store user data and execute queries against it. 
    It is designed to manage multiple users, each with their own knowledge base and data registry, 
    storing supplementary data sources through an import mechanism. 
    
    UserSource applies various metrics to assess the quality of query results and can interact 
    with users for clarification when needed through various contact methods, including email, 
    chat, or other messaging platforms.

    User entries are stored in a JSONSource backend, where each entry contains a reference to a 
    per-user DataRegistry. The DataRegistry itself is backed by its own JSONSource and holds 
    various data and metadata sources, including:
    - a ``"kb"`` KBSource that contains the user's knowledge base data extracted from various sources,
    - a ``"metadata"`` source that contains user metadata, such as preferences and settings,
    - a ``"contact"`` source that contains user contact information in multiple contact methods, and
    - any additional sources added via imports.
    
    Usage::

        us = UserSource({
            "store": {"backend": "file", "path": "users.json"},
            "schema": "schema.json",
        })
        await us.create_user(
            "alice",
            registry_props={"backend": "file", "path": "alice_registry.json"},
            kb_props={"backend": "file", "directory": "alice_kb"},
        )
        results = await us.execute_query("skills", database="alice")
    """

    def __init__(self, props: dict) -> None:
        self._store = _build_json_source(props.get("store", {"backend": "memory"}))
        self._managers: dict[str, UserDataManager] = {}
        if self._store.get("users") is None:
            self._store.set("users", {})
        # Persist schema path; props["schema"] overrides any previously stored value;
        # fall back to the package default when the store has no entry yet.
        if props.get("schema") is not None:
            self._store.set("schema", props["schema"])
        elif self._store.get("schema") is None:
            self._store.set("schema", _DEFAULT_SCHEMA_PATH)

    # ------------------------------------------------------------------ #
    # User management                                                    #
    # ------------------------------------------------------------------ #

    def add_user(self, name: str, registry_props: dict) -> None:
        """Wire up an existing registry that already has a KB registered.

        Assumes the per-user DataRegistry JSONSource (``registry_props``)
        already contains a registered ``"kb"`` source entry, ``"metadata"`` 
        source entry, and ``"contact"`` source entry. 
        
        Use `create_user` to build these sources from scratch.
        """
        manager = UserDataManager(name, registry_props)
        manager.connect()
        self._store.set(f"users.{name}", {"registry": registry_props})
        self._managers[name] = manager

    async def create_user(self, name: str, registry_props: dict, kb_props: dict) -> None:
        """Build a fresh registry + KB, seed schema, and register the user.

        ``kb_props`` is passed directly to ``UserDataManager.initialize``;
        ``schema_path`` from ``UserSource`` props is used as a default if not
        already present in ``kb_props``.
        """
        effective_kb_props = {**kb_props}
        effective_kb_props.setdefault("schema_path", self._store.get("schema"))
        manager = UserDataManager(name, registry_props)
        await manager.initialize(effective_kb_props)
        self._store.set(f"users.{name}", {"registry": registry_props})
        self._managers[name] = manager

    def list_users(self) -> list[str]:
        users = self._store.get("users") or {}
        return list(users.keys())

    def get_user(self, name: str) -> dict | None:
        return self._store.get(f"users.{name}")

    def remove_user(self, name: str) -> None:
        """Remove user from the main store; KB and registry data are untouched."""
        self._store.delete(f"users.{name}")
        self._managers.pop(name, None)

    async def reset_user(self, name: str) -> None:
        await self._get_manager(name).reset(self._store.get("schema"))

    async def delete_user(self, name: str) -> None:
        manager = self._get_manager(name)
        manager.destroy()
        self.remove_user(name)

    # ------------------------------------------------------------------ #
    # Query                                                                #
    # ------------------------------------------------------------------ #

    async def execute_query(
        self,
        query: str,
        database: str,
        optional_properties: dict[str, object] | None = None,
    ) -> list[QueryResult] | str:
        """Execute a natural language query against a user knowledge base.

        optional_properties:
            session     – session identifier string
            output_form – ``"json"`` (default) or ``"nl"``
            top_k       – max results per sub-query (default: 10)
        """
        props = optional_properties or {}
        session_id = str(props["session"]) if "session" in props else None
        output_form = str(props.get("output_form", "json"))
        top_k = int(props["top_k"]) if "top_k" in props else 10

        manager = self._get_manager(database)
        reasoner = UserQueryReasoner(source=self, manager=manager, session_id=session_id)

        rewritten = await reasoner.contextualize_query(query)
        questions = await reasoner.expand_query(rewritten)
        questions.append(rewritten)

        results: list[QueryResult] = []
        for question in questions:
            data, metadata = await manager.execute_query(question, top_k=top_k)
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

    # ------------------------------------------------------------------ #
    # Import                                                               #
    # ------------------------------------------------------------------ #

    async def import_source(
        self,
        source: Any,
        database: str,
        optional_properties: dict[str, object] | None = None,
    ) -> None:
        """Import data from an external source into a user knowledge base."""
        props = optional_properties or {}
        queries: list[str] | None = None
        if "queries" in props:
            raw = props["queries"]
            if isinstance(raw, list):
                queries = [str(q) for q in raw]
        await self._get_manager(database).import_source(source, queries)

    # ------------------------------------------------------------------ #
    # Listing                                                              #
    # ------------------------------------------------------------------ #

    async def list_data(self, database: str) -> list[dict]:
        return await self._get_manager(database).list_data()

    async def list_metadata(self, database: str, source_id: str | None = None) -> list[dict]:
        return await self._get_manager(database).list_metadata(source_id)

    async def describe_data(self, database: str) -> str:
        entries = await self.list_data(database)
        return await UserQueryReasoner(source=self).synthesize_data_nl(entries)

    async def describe_metadata(self, database: str, source_id: str | None = None) -> str:
        entries = await self.list_metadata(database, source_id)
        return await UserQueryReasoner(source=self).synthesize_metadata_nl(entries)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

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
