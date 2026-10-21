from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from blue_data.registry.data_registry import DataRegistry
from blue_data.source.source import DataSource

from blue_data_user_source._sync import run_sync
from blue_data_user_source.data.manager import (
    CLS_JSON_MEMORY,
    CLS_KB_MEMORY,
    DEFAULT_DOC_SOURCE_PROPS,
    DOC_SEARCH_TOP_K,
    UserDataManager,
    _build_json_source,
    _enrich_props,
)
from blue_data_user_source.interaction.contact import ContactManager, ContactMethod
from blue_data_user_source.interaction.session import SessionManager
from blue_data_user_source.reasoning import UserQueryReasoner
from blue_data_user_source.types import (
    QueryError, QueryResult, SessionEndedError, SessionNotFoundError, UserExistsError, UserNotFoundError,
)

# A user's name becomes file and directory names under the data directory, so it
# must be a plain path segment. Same rule as blue-data-kb-source's database names.
_USER_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}")


def validate_user_name(name: Any) -> str:
    """Return *name* if it is a valid user (database) name, else raise ``QueryError``."""
    if not isinstance(name, str) or not _USER_NAME.fullmatch(name):
        raise QueryError(
            f"invalid database name {name!r}: use 1-64 letters, digits, '_' or '-', "
            "starting with a letter, digit or '_'"
        )
    return name


_DEFAULT_SCHEMA_PATH = str(Path(__file__).parent / "data" / "schema.json")
_DEFAULT_METADATA_SCHEMA_PATH = str(Path(__file__).parent / "data" / "metadata_schema.json")
_DEFAULT_CONTACT_SCHEMA_PATH = str(Path(__file__).parent / "data" / "contact_schema.json")
# The stores every user needs; ``doc_source`` is optional (an in-memory default).
_STORE_KEYS = ("registry", "kb_source", "metadata_source", "contact_source", "session_source")


def _as_rows(answer: Any) -> list[dict]:
    """An answer of every output form as ``list[dict]`` rows (blue-data design/14 §1)."""
    if answer is None:
        return []
    if isinstance(answer, list):
        return [row if isinstance(row, dict) else {"value": row} for row in answer]
    if isinstance(answer, dict):
        return [answer]  # include_expanded: {"result": ..., "expanded": ...}
    return [{"answer": answer}]  # output_form="nl": prose

# Built-in per-user collections that carry stats; anything else (e.g. a
# user-added file source) has no stats concept and yields None.
_STATS_COLLECTIONS = ("kb", "metadata", "contacts", "sessions")


def _count_set_leaves(d: dict) -> int:
    """Count non-null leaf values in a nested dict (e.g. metadata's category.key tree)."""
    count = 0
    for v in d.values():
        if isinstance(v, dict):
            count += _count_set_leaves(v)
        elif v is not None:
            count += 1
    return count


def _model_kwarg(model: str | None) -> dict[str, str]:
    """`{"model": …}` when a model was chosen, `{}` otherwise.

    Keeps `UserQueryReasoner`'s own default as the single place the fallback
    lives, rather than repeating "gpt-4o" at every construction site.
    """
    return {"model": model} if model else {}


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
      the user's behalf: identity, preferences, availability, and privacy. Seeded from
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
           "connection": {"protocol": "json/file", "path": "~/.blue-userdb/registry.json"}}

    - ``schema`` — path to the KB graph schema JSON (default: ``data/schema.json``).
      Stored as a property of the source record in the DataRegistry.
    - ``metadata_schema`` — path to the metadata schema JSON
      (default: ``data/metadata_schema.json``). Stored as a source property.
    - ``contact_schema`` — path to the contact schema JSON
      (default: ``data/contact_schema.json``). Stored as a source property.
    - ``console`` — whether the user is at this process's console (default: True).
      Servers pass False: clarification and onboarding then never ask on stdin/stdout,
      and are skipped when no other contact method can reach the user. Describes the
      running process, so it is not stored in the registry.

    Usage::

        us = UserSource("user_source", {
            "registry": {
                "_class": "blue_data.source.json.file_json_source.FileJSONSource",
                "connection": {"protocol": "json/file", "path": "~/.blue-userdb/registry.json"},
            },
            "schema": "/path/to/schema.json",           # optional
            "metadata_schema": "/path/to/metadata.json" # optional
        })
        us.create_database("alice", properties={
            "registry": {
                "_class": "blue_data.source.json.file_json_source.FileJSONSource",
                "connection": {"protocol": "json/file", "path": "~/.blue-userdb/registries/alice.json"},
            },
            "kb_source": {
                "_class": "blue_data_kb_source.file_kb_source.FileKBSource",
                "connection": {"protocol": "kb/file", "directory": "~/.blue-userdb/sources/alice"},
            },
            "metadata_source": {
                "_class": "blue_data.source.json.file_json_source.FileJSONSource",
                "connection": {"protocol": "json/file", "path": "~/.blue-userdb/sources/alice/metadata.json"},
            },
            "contact_source": {
                "_class": "blue_data.source.json.file_json_source.FileJSONSource",
                "connection": {"protocol": "json/file", "path": "~/.blue-userdb/sources/alice/contacts.json"},
            },
        })
        results = us.execute_query("what timezone is alice in?", database="alice")
        us.set_metadata("alice", "preferences.verbosity", "brief")
    """

    # ------------------------------------------------------------------ #
    # DataSource: connection properties / connect API                      #
    # ------------------------------------------------------------------ #

    def _initialize_connection_properties(self) -> None:
        """Declare the connection protocol: ``<family>/<backend>``, family ``user``.

        The base class names the family only. Unlike a SQLSource, a UserSource
        is a composite: the per-user kb/metadata/contact/session/doc backends
        are chosen at ``create_user`` time and may differ between users, so the
        one backend fixed at instantiation is the outer registry's — the
        catalog of which users exist. Each concrete subclass names that
        (``user/file``, ``user/memory``, ``user/redis``); a bare UserSource has
        no registry backend of its own to name, so it reports ``user``.
        """
        conn = self.properties.get("connection", {})
        conn.setdefault("protocol", "user")
        self.properties["connection"] = conn

    def _connect(self, **connection) -> DataRegistry:  # noqa: ARG002 — no live socket; see class docstring
        """Build the outer DataRegistry backed by the JSONSource from ``properties["registry"]``.

        Called automatically by ``DataSource.__init__`` (via ``_start()`` ->
        ``_start_connection()``), before the rest of ``__init__`` runs. The
        registry is returned so it's tracked as ``self.connection`` per the
        base class's lifecycle contract, and cached as ``self._registry`` for
        use throughout this class. Also (re)initializes the per-user
        ``UserDataManager`` cache, so a manual reconnect (``_connect()``
        called again) starts with a clean cache.

        ``**connection`` (``self.properties["connection"]``, e.g. its
        ``protocol`` label) is unused here — the registry's own backend is
        configured separately via ``properties["registry"]``.
        """
        registry_json_props = self.properties.get("registry") or {
            "_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}
        }
        registry_store = _build_json_source(f"{self.name}_registry", registry_json_props)
        self._registry = DataRegistry(store=registry_store)
        self._managers: dict[str, UserDataManager] = {}
        return self._registry

    def _disconnect(self) -> None:
        self._registry = None
        self._managers = {}

    def __init__(self, name: str = "user_source", properties: dict | None = None) -> None:
        super().__init__(name, properties)
        # self._registry and self._managers are built by _connect(), invoked
        # automatically above via DataSource.__init__ -> _start() -> _start_connection().

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
                    **{k: v for k, v in self.properties.items() if k != "console"},
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

    @property
    def console(self) -> bool:
        """Whether the user is at this process's console; see the ``console`` prop."""
        return bool(self.properties.get("console", True))

    # ------------------------------------------------------------------ #
    # DataSource: database = user                                          #
    # ------------------------------------------------------------------ #

    def fetch_databases(self) -> list[str]:
        return self.list_users()

    def fetch_database_metadata(self, database: str) -> dict:
        return self.get_user(database) or {}


    def default_user_props(self, name: str) -> dict[str, dict]:
        """The store configs a new user gets when none are given: all in memory.

        Keyed like ``create_database``'s properties (``registry``, ``kb_source``,
        ``metadata_source``, ``contact_source``, ``session_source``, and
        optionally ``doc_source``). Backend subclasses override this to keep a
        user's stores where the class keeps its registry; a store left out has
        no default and must be given.
        """
        validate_user_name(name)
        memory_json = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
        return {
            "registry": dict(memory_json),
            "kb_source": {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}},
            "metadata_source": dict(memory_json),
            "contact_source": dict(memory_json),
            "session_source": dict(memory_json),
        }

    def create_database(
        self, database: str, properties: dict | None = None, overwrite: bool = False,
    ) -> dict:
        """Create a new user, synchronously (the ``DataSource`` interface).

        Store configs come from :meth:`default_user_props`; any of
        ``registry``, ``kb_source``, ``metadata_source``, ``contact_source``,
        ``session_source`` or ``doc_source`` in *properties* replaces that one
        default. A store with no default that is not given raises ``QueryError``.

        ``overwrite`` deletes an existing user of that name first; without it an
        existing user raises ``UserExistsError``. Unlike :meth:`create_user`, this
        does not onboard unless ``properties["onboard"]`` is true: a synchronous
        call should not start an interview on whatever terminal it runs under.
        """
        p = {**self.default_user_props(database), **(properties or {})}
        missing = [key for key in _STORE_KEYS if not isinstance(p.get(key), dict)]
        if missing:
            raise QueryError(
                f"Cannot create {database!r}: {type(self).__name__} has no default for "
                f"{', '.join(missing)}; pass {'it' if len(missing) == 1 else 'them'} in properties."
            )
        if overwrite and database in self.list_users():
            run_sync(self.delete_user(database))
        run_sync(self.create_user(
            database,
            registry_props=p["registry"],
            kb_source_props=p["kb_source"],
            metadata_source_props=p["metadata_source"],
            contact_source_props=p["contact_source"],
            session_source_props=p["session_source"],
            doc_source_props=p.get("doc_source"),
            onboard=bool(p.get("onboard", False)),
            onboard_metadata=bool(p.get("onboard_metadata", True)),
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
    # DataSource: schema / entity / relation introspection                 #
    # ------------------------------------------------------------------ #

    def fetch_metadata(self) -> dict:
        """Source-level metadata: user count and the schema paths new users are seeded from."""
        return {
            "name": self.name,
            "user_count": len(self.list_users()),
            "schema": self._registry.get_source_property(self.name, "schema"),
            "metadata_schema": self._registry.get_source_property(self.name, "metadata_schema"),
            "contact_schema": self._registry.get_source_property(self.name, "contact_schema"),
        }

    def fetch_schema(self) -> dict:
        """The template KB schema every new user's ``kb`` collection is seeded from.

        This is the declared schema (``data/schema.json`` by default), not any
        one user's live schema — see :meth:`fetch_database_schema` for that.
        """
        schema_path = self._registry.get_source_property(self.name, "schema") or _DEFAULT_SCHEMA_PATH
        return json.loads(Path(schema_path).read_text())

    def fetch_database_schema(self, database: str) -> dict:
        """A user's live KB schema — ``{"entities", "relations", "subclasses"}`` —
        including any expansion (new classes/properties) since onboarding."""
        manager = self._get_manager(database)
        return run_sync(manager._ensure_kb_source().export_database_schema(manager._database))

    def fetch_database_collection_entities(self, database: str, collection: str) -> dict:
        """Entity type definitions for ``collection``. Only ``"kb"`` has entities —
        the JSON-backed collections (metadata/contacts/sessions) have none."""
        if collection != "kb":
            return {}
        return self.fetch_database_schema(database).get("entities", {})

    def fetch_database_collection_relations(self, database: str, collection: str) -> dict:
        """Relation type definitions for ``collection``. Only ``"kb"`` has relations."""
        if collection != "kb":
            return {}
        return self.fetch_database_schema(database).get("relations", {})

    # ------------------------------------------------------------------ #
    # DataSource: query                                                    #
    # ------------------------------------------------------------------ #

    async def async_execute_query(
        self,
        query: str,
        database: str | None = None,
        optional_properties: dict | None = None,
    ) -> tuple[Any, str]:
        """Answer *query* and return ``(answer, session_id)``: UserSource's own query API.

        The answer is a list of dicts for ``output_form="json"`` (the default),
        prose for ``"nl"``, or ``{"result", "expanded"}`` with ``include_expanded``.
        ``session_id`` is the reused or newly-created session this query landed in
        (see "session" in optional_properties). The CLI, MCP server and REST API use
        this; :meth:`execute_query` is the ``DataSource`` form.
        """
        return await self._run_query(query, database, optional_properties=optional_properties)

    def execute_query(
        self,
        query,
        database: str | None = None,
        collection: str | None = None,
        optional_properties: dict | None = None,
    ) -> list[dict]:
        """Answer *query* as ``list[dict]`` rows, as blue-data's DataSource contract requires.

        The rows are the answer of :meth:`async_execute_query`: its table for
        ``"json"``, one ``{"answer": ...}`` row for ``"nl"``, one
        ``{"result", "expanded"}`` row with ``include_expanded``. The session id
        does not ride along (design/14 §1); a caller that needs it creates the
        session first (:meth:`create_session`) and passes it as
        ``optional_properties["session"]``, or uses :meth:`async_execute_query`.
        """
        answer, _session_id = run_sync(
            self._run_query(query, database, collection, optional_properties)
        )
        return _as_rows(answer)

    def execute_query_nl(
        self,
        query: str,
        database: str | None = None,
        collection: str | None = None,
        schema: dict | None = None,    # noqa: ARG002 — UserSource uses its own reasoner
        llm_fn=None,                   # noqa: ARG002 — see below
        optional_properties: dict | None = None,
    ) -> list[dict]:
        """The same as :meth:`execute_query`: the query is already natural language.

        ``llm_fn`` and ``schema`` are accepted, as the registry passes them, but not
        used: an allowed exception to the DataSource contract (as in
        blue-data-kb-source). Answering runs this source's own reasoning pipeline,
        rewriting, expansion, quality assessment and clarification, which a plain
        ``llm_fn(prompt) -> text`` cannot drive. The model is
        ``optional_properties["model"]``, else ``gpt-4o``.
        """
        return self.execute_query(query, database, collection, optional_properties)

    # ------------------------------------------------------------------ #
    # DataSource: import                                                   #
    # ------------------------------------------------------------------ #

    def import_data(
        self,
        source: Any,
        database: str = "default",
        collection: str = "default",
        entity: str | None = None,
        mode: str = "append",
        options: dict | None = None,
    ) -> dict:
        """Signature matches ``DataSource.import_data`` (``database`` before
        ``collection``, both defaulted) — a positional call valid against the
        base class binds the same arguments here."""
        return run_sync(
            self._get_manager(database).import_data(source, collection, entity, mode, options)
        )

    # ------------------------------------------------------------------ #
    # DataSource: stats                                                    #
    # ------------------------------------------------------------------ #

    def fetch_source_stats(self) -> dict | None:
        return {"user_count": len(self.list_users())}

    def fetch_database_stats(self, database: str) -> dict | None:
        if database not in self.list_users():
            return None
        collections = self.fetch_database_collections(database)
        stats: dict[str, Any] = {"collections": collections}
        for c in collections:
            if c in _STATS_COLLECTIONS:
                stats[c] = self.fetch_collection_stats(database, c)
        return stats

    def fetch_collection_stats(
        self,
        database: str,
        collection: str,
        entities: list | None = None,
        relations: list | None = None,
        sample_limit: int | None = None,
    ) -> dict | None:
        manager = self._get_manager(database)
        if collection == "kb":
            return self._fetch_kb_collection_stats(manager, entities, relations, sample_limit)
        if collection == "metadata":
            return {"keys_set": _count_set_leaves(manager.list_metadata())}
        if collection == "contacts":
            contacts = manager.get_contacts()
            return {"methods": sum(len(names) for names in contacts.values())}
        if collection == "sessions":
            sessions = run_sync(self._session_manager(database).list_sessions())
            return {"sessions": len(sessions)}
        return None

    def _fetch_kb_collection_stats(
        self,
        manager: UserDataManager,
        entities: list | None,
        relations: list | None,
        sample_limit: int | None,
    ) -> dict:
        rows = run_sync(manager._ensure_kb_source().fetch_database_data(manager._database, compact=True))
        by_class: dict[str, int] = {}
        sample_entities: list[str] = []
        for r in rows:
            if r.get("relation_type") != "IS_INSTANCE_OF":
                continue
            cls = r.get("class_name")
            if entities is not None and cls not in entities:
                continue
            by_class[cls] = by_class.get(cls, 0) + 1
            if sample_limit and len(sample_entities) < sample_limit:
                sample_entities.append(r.get("entity_name"))
        by_relation: dict[str, int] = {}
        for r in rows:
            if r.get("relation_type") != "REPRESENTS":
                continue
            rel = r.get("relation_name")
            if relations is not None and rel not in relations:
                continue
            by_relation[rel] = by_relation.get(rel, 0) + 1
        result: dict[str, Any] = {
            "entity_count": sum(by_class.values()),
            "entities_by_class": by_class,
            "fact_count": sum(by_relation.values()),
            "facts_by_relation": by_relation,
        }
        if sample_limit:
            result["sample_entities"] = sample_entities
        return result

    def fetch_entity_stats(
        self,
        database: str,
        collection: str,
        entity: str,
        sample_limit: int | None = None,
        row_sample_size: int | None = None,
    ) -> dict | None:
        """Instance count and per-property fill counts for the ``entity`` class in ``"kb"``.

        ``row_sample_size`` (the DataSource contract's name, design/14 §5) or its
        older alias ``sample_limit`` caps the number of instance names returned
        under ``"sample"``, used by the ``get_sample`` NL tool.
        """
        if collection != "kb":
            return None
        if row_sample_size is not None:
            sample_limit = row_sample_size
        manager = self._get_manager(database)
        rows = run_sync(manager._ensure_kb_source().fetch_database_data(manager._database, compact=True))
        instance_names = {
            r["entity_name"] for r in rows
            if r.get("relation_type") == "IS_INSTANCE_OF" and r.get("class_name") == entity
        }
        prop_counts: dict[str, int] = {}
        for r in rows:
            if (
                r.get("relation_type") == "IS_VALUE_OF"
                and r.get("owner_label") == "ENTITY"
                and r.get("entity_name") in instance_names
            ):
                prop = r.get("property_name")
                prop_counts[prop] = prop_counts.get(prop, 0) + 1
        result: dict[str, Any] = {
            "entity": entity, "count": len(instance_names), "properties": prop_counts,
        }
        if sample_limit:
            result["sample"] = sorted(instance_names)[:sample_limit]
        return result

    def fetch_property_stats(
        self,
        database: str,
        collection: str,
        entity: str,
        property_name: str,
        sample_limit: int | None = None,
    ) -> dict | None:
        """Value/null/distinct counts (and a sample of distinct values) for one
        property across all instances of ``entity`` in ``"kb"``."""
        if collection != "kb":
            return None
        manager = self._get_manager(database)
        rows = run_sync(manager._ensure_kb_source().fetch_database_data(manager._database, compact=True))
        instance_names = {
            r["entity_name"] for r in rows
            if r.get("relation_type") == "IS_INSTANCE_OF" and r.get("class_name") == entity
        }
        values = [
            r["property_value"] for r in rows
            if r.get("relation_type") == "IS_VALUE_OF"
            and r.get("owner_label") == "ENTITY"
            and r.get("entity_name") in instance_names
            and r.get("property_name") == property_name
        ]
        distinct = sorted({v for v in values}, key=str)
        result: dict[str, Any] = {
            "entity": entity,
            "property": property_name,
            "count": len(values),
            "distinct_count": len(distinct),
            "null_count": len(instance_names) - len(values),
        }
        if sample_limit:
            result["sample_values"] = distinct[:sample_limit]
        return result

    # ------------------------------------------------------------------ #
    # DataSource: generic NL2Q tools                                       #
    # ------------------------------------------------------------------ #

    def get_nl_tools(self, database: str | None = None, collection: str | None = None) -> list[dict]:
        """Base tool set, with ``execute_query`` reworded: UserSource has no
        separate native query language — it takes natural language directly."""
        tools = super().get_nl_tools(database=database, collection=collection)
        for tool in tools:
            if tool["name"] == "execute_query":
                tool["description"] = (
                    "Answer a natural language question about the user's personal data. "
                    "There is no separate native query language — pass plain text."
                )
                tool["input_schema"]["properties"]["query"]["description"] = (
                    "Natural language question, e.g. \"what timezone is the user in?\""
                )
        return tools

    def execute_nl_tool(
        self,
        name: str,
        tool_input: dict,
        database: str | None = None,
        collection: str | None = None,
        optional_properties: dict | None = None,
        read_only: bool = True,  # noqa: ARG002 — every tool here only reads
    ):
        """Dispatch a single NL-tool call (see ``DataSource.get_nl_tools``).

        Overridden rather than inherited because ``execute_query`` here takes
        natural language directly (no native-query stage), and because
        ``get_sample`` passes the requested sample size through to
        :meth:`fetch_entity_stats`. ``read_only`` is the contract's flag
        (design/14 §5); every tool this source offers only reads, so it changes
        nothing here.
        """
        db = tool_input.get("database", database)
        coll = tool_input.get("collection", collection)

        if name == "list_databases":
            return self.fetch_databases()
        if name == "list_collections":
            return self.fetch_database_collections(db)
        if name == "get_schema":
            return {
                "entities": self.fetch_database_collection_entities(db, coll),
                "relations": self.fetch_database_collection_relations(db, coll),
            }
        if name == "get_metadata":
            return self.fetch_database_collection_metadata(db, coll)
        if name == "execute_query":
            return self.execute_query(
                tool_input["query"], database=db, collection=coll,
                optional_properties=optional_properties,
            )
        if name == "get_sample":
            return self.fetch_entity_stats(
                db, coll, tool_input["entity"],
                row_sample_size=tool_input.get("sample_size", 10),
            )
        if name == "get_column_stats":
            return self.fetch_property_stats(db, coll, tool_input["entity"], tool_input["column"])
        if name == "get_relations":
            return self.fetch_database_collection_relations(db, coll)
        raise ValueError(f"Unknown tool: {name!r}")

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
        onboard: bool = True,
        onboard_metadata: bool = True,
    ) -> None:
        """Build a fresh per-user registry + all sources, seed schema, register the user.

        When ``onboard`` is True (the default), also runs :meth:`onboard_user`
        immediately afterward to ask the new user a few questions to seed
        their data and metadata. ``onboard_metadata`` (default True) controls
        whether that onboarding also asks structured metadata questions —
        set to False to only seed the KB.

        Raises ``QueryError`` for an invalid name, and ``UserExistsError`` for a
        user that is already registered, before anything is written: creating
        it again re-registered the name against new stores, orphaning the
        existing user's data (#141).
        """
        validate_user_name(name)
        if self.get_user(name) is not None:
            raise UserExistsError(f"Database {name!r} already exists.")
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
        if onboard:
            await self.onboard_user(name, include_metadata=onboard_metadata)

    async def onboard_user(
        self, name: str, include_metadata: bool = True, model: str | None = None
    ) -> None:
        """Ask a user a few onboarding questions to seed their KB data and metadata.

        Called automatically by :meth:`create_user` (unless ``onboard=False``
        was passed), and can also be re-run later for an existing user —
        metadata questions are only generated for keys still unset.

        ``include_metadata`` (default True) controls whether the structured
        metadata question batch is asked; set to False to only seed the KB
        (plus the always-asked name, which also seeds ``identity.name``).
        """
        manager = self._get_manager(name)
        reasoner = UserQueryReasoner(source=self, manager=manager, **_model_kwarg(model))
        await reasoner.onboard(
            metadata_schema_path=self._registry.get_source_property(self.name, "metadata_schema"),
            include_metadata=include_metadata,
        )

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
        """Register a file as a source in the user's KB and optionally extract via queries.

        ``optional_properties``: ``queries``, ``name``, ``description``,
        ``original``, ``effort``, and ``location`` (the label recorded on the
        SOURCE node; defaults to the file's path).
        """
        await self._get_manager(database).add_source(source, **self._source_kwargs(optional_properties))

    async def add_text_source(
        self,
        text: str,
        database: str,
        optional_properties: dict[str, object] | None = None,
    ) -> None:
        """Add *text* as a source, without a file: nothing is read from or written to disk.

        Same ``optional_properties`` as :meth:`add_source`; ``location``
        defaults to ``"text:<name>"``. The REST API uses this, so a request
        never names, or leaves behind, a server path (#133, #151).
        """
        await self._get_manager(database).add_source(None, text=text, **self._source_kwargs(optional_properties))

    @staticmethod
    def _source_kwargs(optional_properties: dict[str, object] | None) -> dict[str, Any]:
        props = optional_properties or {}
        queries: list[str] | None = None
        if isinstance(props.get("queries"), list):
            queries = [str(q) for q in props["queries"]]  # type: ignore[union-attr]
        return {
            "queries": queries,
            "name": str(props["name"]) if "name" in props else None,
            "description": str(props["description"]) if "description" in props else None,
            "original": str(props["original"]) if "original" in props else None,
            "effort": str(props.get("effort", "medium")),
            "location": str(props["location"]) if "location" in props else None,
        }

    async def remove_source(self, database: str, source_name: str) -> dict[str, Any]:
        """Remove a source by name or id: its document chunks and its KB SOURCE node.

        Facts extracted from it are kept. See ``UserDataManager.remove_source``.
        """
        return await self._get_manager(database).remove_source(source_name)

    # ------------------------------------------------------------------ #
    # Listing                                                              #
    # ------------------------------------------------------------------ #

    async def list_data(self, database: str) -> list[dict]:
        return await self._get_manager(database).list_data()

    async def list_sources(self, database: str, source_id: str | None = None) -> list[dict]:
        return await self._get_manager(database).list_sources(source_id)

    async def describe_data(self, database: str, model: str | None = None) -> str:
        entries = await self.list_data(database)
        reasoner = UserQueryReasoner(source=self, **_model_kwarg(model))
        return await reasoner.synthesize_data_nl(entries)

    async def describe_sources(
        self, database: str, source_id: str | None = None, model: str | None = None
    ) -> str:
        entries = await self.list_sources(database, source_id)
        reasoner = UserQueryReasoner(source=self, **_model_kwarg(model))
        return await reasoner.synthesize_metadata_nl(entries)

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
        return ContactManager(
            database=database, data_manager=self._get_manager(database), console=self.console
        )

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
        self,
        database: str,
        protocol: str,
        name: str,
        details: dict[str, Any] | None = None,
        preference: int | None = None,
        **fields: Any,
    ) -> None:
        """``details`` replaces the stored fields; ``fields`` set individual ones. See ContactManager."""
        await self._contact_manager(database).update_contact_method(
            protocol, name, details=details, preference=preference, **fields
        )

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

        ``output_form`` ("json", default, or "nl") controls the format of the
        synthesized answer: "json" returns a single aggregated table (a list of
        dicts sharing a schema derived from the query); "nl" returns prose.

        ``include_expanded`` (default False) is orthogonal to ``output_form``:
        when True, the per-sub-question queries and their raw results are also
        returned alongside the synthesized answer, in the same output_form
        (a list of ``{"query", "results"}`` dicts for "json", or a short prose
        summary organized by topic for "nl").

        ``max_interaction_rounds`` (default 3) bounds how many times the user is
        asked for clarification when quality metrics fail; the loop stops early
        once all metrics pass.

        ``top_k`` (default 5) caps the chunks taken from each document store
        (``session_content``, ``external_documents``) per sub-question.
        """
        props = optional_properties or {}
        output_form = str(props.get("output_form", "json"))
        include_expanded = bool(props.get("include_expanded", False))
        top_k = props.get("top_k", DOC_SEARCH_TOP_K)
        # bool is an int, and top_k=True would quietly mean 1.
        if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
            raise QueryError(f"top_k must be a positive integer, got {top_k!r}.")

        manager = self._get_manager(database)
        session_manager = self._session_manager(database)
        if "session" in props:
            session_id = str(props["session"])
            session = await session_manager.get_session(session_id)
            if session is None:
                raise SessionNotFoundError(f"Unknown session {session_id!r}")
            if session.get("status") == "ended":
                raise SessionEndedError(f"Session {session_id!r} has ended; cannot add a query to it.")
        else:
            session_id = await session_manager.create_session()
        query_id = await session_manager.create_query(session_id, query, output_form)

        reasoner = UserQueryReasoner(
            source=self, manager=manager, session_id=session_id, query_id=query_id,
            **_model_kwarg(props.get("model")),
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
                top_k=top_k,
            )
            for q in questions
        ]))

        # Aggregate data + metadata across all sub-questions for a single quality pass
        all_data: list[Any] = [item for data, _ in raw_results for item in data]
        all_metadata: dict[str, Any] = {}
        for _, meta in raw_results:
            all_metadata.update(meta)

        results: list[QueryResult] = [
            QueryResult(query=q, results=data)
            for q, (data, _) in zip(questions, raw_results)
        ]

        # Phase 3: assess aggregate quality, resolving via user interaction if needed
        max_rounds = int(props.get("max_interaction_rounds", 3))
        new_items = await reasoner.resolve_via_interaction(
            query, rewritten, all_data, all_metadata, max_rounds=max_rounds
        )
        # Surface the user's responses (one per round) as a separate result
        if new_items:
            results.append(QueryResult(query=query, results=new_items))

        if output_form == "nl":
            answer: Any = await reasoner.synthesize_results_nl(query, results)
        else:
            answer = await reasoner.synthesize_results_json(query, results)

        if not include_expanded:
            return answer, session_id

        if output_form == "nl":
            expanded: Any = await reasoner.synthesize_expanded_nl(results)
        else:
            expanded = [{"query": r.query, "results": r.results} for r in results]

        return {"result": answer, "expanded": expanded}, session_id

    def _get_manager(self, name: str) -> UserDataManager:
        if name not in self._managers:
            db_props = self.get_user(name)
            if db_props is None:
                raise UserNotFoundError(f"User not found: {name!r}")
            registry_props = db_props.get("registry") or {
                "_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}
            }
            doc_source_props = db_props.get("doc_source") or DEFAULT_DOC_SOURCE_PROPS
            manager = UserDataManager(name, registry_props, doc_source_props=doc_source_props)
            manager.connect()
            self._managers[name] = manager
        return self._managers[name]
