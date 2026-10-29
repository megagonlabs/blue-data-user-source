from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Literal

from blue_data.core.utils.path_utils import contain
from blue_data.registry.data_registry import DataRegistry
from blue_data.source.source import DataSource
from blue_data_kb_source.kb_source import KBSource

from blue_data_user_source.data.paths import get_path

logger = logging.getLogger(__name__)

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
CLS_VECTOR_MEMORY = "blue_data.source.vector.memory_vector_source.MemoryVectorSource"
CLS_VECTOR_FILE   = "blue_data.source.vector.file_vector_source.FileVectorSource"

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
_VECTOR_BACKENDS: dict[str, str] = {
    "memory": CLS_VECTOR_MEMORY,
    "file":   CLS_VECTOR_FILE,
}
_BACKEND_CLASSES: dict[str, dict[str, str]] = {
    "kb": _KB_BACKENDS,
    "json": _JSON_BACKENDS,
    "vector": _VECTOR_BACKENDS,
}

# Default embedding model + vector backend for per-session interaction-transcript
# DocumentDataSources when the caller doesn't supply doc_source_props explicitly.
DEFAULT_DOC_SOURCE_PROPS: dict = {
    "embedding_model": "dummy",
    "vector_source": {"backend": "memory"},
}

# Max chunks retrieved per non-KB source (session_content, external_documents)
# for each execute_query call.
DOC_SEARCH_TOP_K = 5

# Registry record names are embedded verbatim in the record's storage key
# (Registry._record_key: f"{scope}/{type}/{name}"), and that key is then
# interpreted by the underlying JSON store as a *dot-notation* path
# (json_query_set / _path_parts splits on "."). So a name containing "."
# (e.g. a file's extension, as in "resume.txt") silently nests the record
# under a bogus intermediate key instead of storing it flat — and a name
# containing "/" produces a name that reads like a nested path even though
# it happens not to corrupt the key. Strip both so registered names are
# always safe, flat, single-segment keys.
_NAME_SEPARATOR_REPLACEMENT = "__SEP__"

# Registry record type that maps a KB SOURCE id to its document in
# "external_documents" (document_id + chunk_count) — see add_source.
_DOCUMENT_RECORD = "document"
_UNSAFE_NAME_CHARS = ("/", "\\", ".")


def sanitize_registry_name(name: str) -> str:
    """Replace path- and dot-notation-unsafe characters so *name* is safe as a registry record name."""
    sanitized = name
    for ch in _UNSAFE_NAME_CHARS:
        sanitized = sanitized.replace(ch, _NAME_SEPARATOR_REPLACEMENT)
    return sanitized


def _enrich_props(props: dict, kind: str) -> dict:
    """Normalise *props* to ``{"_class": "...", "connection": {...}}``.

    Pass-through when *props* already has ``_class``.  Falls back to the
    legacy ``{"backend": "..."}`` shape for backward compatibility when
    reading old stored configs.
    """
    if "_class" in props:
        return props
    backend = props.get("backend", "memory")
    backends = _BACKEND_CLASSES[kind]
    cls = backends.get(backend)
    if cls is None:
        raise ValueError(f"Unknown {kind} backend: {backend!r}")
    return {"_class": cls, "connection": props}


def _expand_user_paths(props: Any) -> Any:
    """A copy of *props* with ``~`` expanded in every ``path`` and ``directory`` it holds.

    The file stores (blue-data's ``FileJSONSource``, kb-source's ``FileKBSource``,
    the document vector store) use a path as given, so ``~/x`` was written to a
    literal ``./~/x`` while delete expanded it to ``$HOME/x`` and removed another
    store's files (#171). Store configs are expanded once, before a user's
    stores are built and recorded, so the path recorded is the path written.
    """
    if isinstance(props, dict):
        return {
            k: str(Path(v).expanduser()) if k in ("path", "directory") and isinstance(v, str)
            else _expand_user_paths(v)
            for k, v in props.items()
        }
    if isinstance(props, list):
        return [_expand_user_paths(v) for v in props]
    return props


def _build_embedding_model(spec: str | dict | None) -> Any:
    """Build an EmbeddingModel from a simple string spec ('dummy' or 'openai').

    Live embedding-model objects can't round-trip through the registry's
    generic _class/connection reconnection path, so callers that need one
    (currently only per-session DocumentDataSource construction) build it
    directly from this small string switch instead.
    """
    from blue_data_doc_source import DummyEmbeddingModel, OpenAIEmbeddingModel

    name = spec if isinstance(spec, str) else (spec or {}).get("name", "dummy")
    if name == "dummy":
        return DummyEmbeddingModel()
    if name == "openai":
        return OpenAIEmbeddingModel()
    raise ValueError(f"Unknown embedding model: {name!r}")


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
    - ``"sessions"`` (JSONSource) — session / query / interaction records.
    - ``"session_content"`` (DocumentDataSource) — shared across all sessions;
      holds every session's interaction transcripts (one file per interaction),
      created on demand via :meth:`ensure_session_doc_source`. Unlike the sources
      above, it is NOT reconstructed via the registry's generic
      ``connect_source`` path — its embedding model is a live object that can't
      round-trip through ``_class``/``connection`` reflection, so this manager
      rebuilds and caches it itself from ``doc_source_props``.
    - ``"external_documents"`` (DocumentDataSource) — shared across all files
      registered via :meth:`add_source` (e.g. ``blue-userdb data source add``); every
      file is parsed, chunked, and embedded into this source so it can later
      be searched or used to answer queries. Created on demand via
      :meth:`ensure_external_documents_source`; same non-reconnected caching
      as ``session_content``, but kept in a separate collection so the two
      don't mix.

    :meth:`execute_query` answers against ``"kb"`` and augments the result
    with the top matching chunks from ``"session_content"`` and
    ``"external_documents"`` (via ``DOCUMENT.SEARCH``), each tagged with a
    ``"source"`` field so callers can tell provenance apart.

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

    def __init__(
        self,
        database: str,
        registry_props: dict,
        doc_source_props: dict | None = None,
        data_root: str | Path | None = None,
    ) -> None:
        self._database = database
        self._registry_props = registry_props
        self._doc_source_props = doc_source_props or DEFAULT_DOC_SOURCE_PROPS
        # The directory every file this user's stores record must lie under for
        # delete and reset to remove it (#156); None when the source keeps no files.
        self._data_root = Path(data_root) if data_root is not None else None
        self._refused: list[str] = []
        self._registry: DataRegistry | None = None
        # Optional overrides — set directly by callers (e.g. test mocks)
        self._kb_source: Any = None
        self._metadata_source: Any = None
        self._contact_source: Any = None
        self._session_source: Any = None
        self._session_doc_source: Any = None
        self._external_doc_source: Any = None

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
        session_source_props: dict,
    ) -> None:
        """Create the per-user DataRegistry, instantiate + register all sources, seed schemas."""
        registry_store = _build_json_source("registry", self._registry_props)
        self._registry = DataRegistry(store=registry_store)

        # KB source. Extra top-level keys (e.g. "search", for the KB's
        # schema/data search index config) pass through alongside "connection" —
        # same convention as _build_json_source's "namespace" passthrough.
        kb_enriched = _enrich_props(kb_source_props, "kb")
        kb_extra = {k: v for k, v in kb_enriched.items() if k not in ("_class", "connection")}
        kb_source = DataSource.instantiate(
            kb_enriched["_class"], "kb",
            properties={"connection": kb_enriched.get("connection", {}), **kb_extra},
        )
        self._registry.register_source(kb_source)
        await self.seed_kb_source_schema(schema_path)
        await self.seed_user_entity()

        # Metadata, contacts and sessions go through _build_json_source so that
        # top-level keys such as Redis's "namespace" reach the store; without it
        # every user's stores share the backend's default keys (#136).
        meta_source = _build_json_source("metadata", metadata_source_props)
        self._registry.register_source(meta_source)
        if metadata_schema_path:
            self.seed_metadata_schema(metadata_schema_path)

        # Contacts source
        cont_source = _build_json_source("contacts", contact_source_props)
        self._registry.register_source(cont_source)
        if contact_schema_path:
            self.seed_contact_schema(contact_schema_path)

        # Sessions source — no fixed schema; session records are created on demand.
        sess_source = _build_json_source("sessions", session_source_props)
        self._registry.register_source(sess_source)

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
        """Clear and reseed selected sources back to schema defaults.

        Files are removed only inside the data directory (#156); see
        :meth:`destroy`. Paths refused are logged and kept in ``refused_paths``.
        """
        self._refused = []
        if sources is None:
            sources = {"kb", "metadata", "contacts", "sessions"}

        if "kb" in sources:
            await self.clear_kb()
            # Ingested documents go with the KB that records them (its SOURCE
            # nodes): left on disk, they came back in the next query (#144).
            self._clear_external_documents()
            if schema_path:
                await self.seed_kb_source_schema(schema_path)
                await self.seed_user_entity()

        if "metadata" in sources:
            self.clear_metadata()
            if metadata_schema_path:
                self.seed_metadata_schema(metadata_schema_path)

        if "contacts" in sources:
            self.clear_contacts()
            if contact_schema_path:
                self.seed_contact_schema(contact_schema_path)

        if "sessions" in sources:
            self.clear_sessions()

        # Deregister any additional imported sources from the registry, including
        # the shared "session_content" and "external_documents" doc sources.
        self._session_doc_source = None
        self._external_doc_source = None
        source_records = self._registry.list_records(record_type="source", scope="/")
        for record in source_records:
            if record["name"] not in ("kb", "metadata", "contacts", "sessions"):
                self._registry.deregister(record)

    def _contained(self, path: str | Path) -> Path | None:
        """*path* if it lies inside the data root, else ``None``, refused and logged.

        A path recorded in a store's connection settings may have been written
        by another tool, an older version or a shared registry, so delete and
        reset remove nothing outside this user's data directory (#156). Each
        component is checked with blue-data's ``contain()``, which resolves
        symlinks, so a link inside the root that points out of it is refused too.

        *path* is read as the store reads it, without expanding ``~``: a record
        from before #171 that holds ``~/x`` names the ``./~/x`` its store wrote,
        not ``$HOME/x``, where another store's files may live.
        """
        if self._data_root is None:
            return self._refuse(path, "this source keeps no data directory to contain it in")
        target = Path(os.path.normpath(Path(path).absolute()))
        for root in (Path(os.path.normpath(self._data_root.absolute())), self._data_root.resolve()):
            try:
                parts = target.relative_to(root).parts
                break
            except ValueError:
                continue
        else:
            return self._refuse(path, f"outside the data directory {str(self._data_root)!r}")
        if not parts:
            return self._refuse(path, "it is the data directory itself")
        current = str(self._data_root)
        try:
            for part in parts:
                current = contain(current, part)
        except ValueError as exc:
            return self._refuse(path, str(exc))
        return Path(current)

    @property
    def refused_paths(self) -> list[str]:
        """The recorded paths the last destroy or reset would not delete."""
        return list(self._refused)

    def _refuse(self, path: str | Path, why: str) -> None:
        logger.warning("Not deleting %s for %r: %s", path, self._database, why)
        self._refused.append(str(path))
        return None

    def _unlink(self, path: str | Path) -> None:
        contained = self._contained(path)
        if contained is not None:
            contained.unlink(missing_ok=True)

    def _unlink_store_file(self, path: str | Path) -> None:
        """Remove a store's file and the ``<file>.lock`` sidecar its locking leaves (#179).

        The sidecar sits beside the file, so it is removed only when the file is.
        """
        contained = self._contained(path)
        if contained is not None:
            contained.unlink(missing_ok=True)
            contained.with_name(f"{contained.name}.lock").unlink(missing_ok=True)

    def _rmtree(self, path: str | Path) -> None:
        contained = self._contained(path)
        if contained is not None and contained.exists():
            shutil.rmtree(contained)

    def destroy(self) -> list[str]:
        """Delete this user's stored data: backing files, and namespaced stores (e.g. Redis).

        A store with neither a file path nor its own ``namespace`` is left
        alone: before #136 such stores shared the backend's default keys with
        every other user, so clearing "its" keys would delete theirs. A recorded
        file path outside the data directory is left alone too (#156); the
        paths refused are returned (and logged).
        """
        self._refused = []
        user_dir: Path | None = None
        if self._registry is not None:
            # KB — file backend stores {database}.json inside the directory
            kb_props = self._registry.get_source_properties("kb") or {}
            kb_conn = kb_props.get("connection", {})
            if "directory" in kb_conn:
                user_dir = self._contained(kb_conn["directory"])
                if user_dir is not None:
                    self._unlink_store_file(user_dir / f"{self._database}.json")
                    self._unlink(user_dir / f".{self._database}.lock")  # the KB's write lock

            # Metadata, contacts, and sessions — a file, or a namespaced store
            # whose keys used to be left behind on Redis (#153).
            for src_name in ("metadata", "contacts", "sessions"):
                props = self._registry.get_source_properties(src_name) or {}
                conn = props.get("connection", {})
                if "path" in conn:
                    self._unlink_store_file(conn["path"])
                elif props.get("namespace"):
                    self._registry.connect_source(src_name).delete(None)
                elif conn.get("protocol", "").startswith("json/redis"):
                    logger.warning(
                        "Not clearing %s store of %r: it has no namespace of its own and may hold other users' data",
                        src_name, self._database,
                    )

        # Session content — vector store + raw transcripts directory, if file-backed
        session_content_dir = self._session_vector_directory()
        if session_content_dir is not None:
            self._rmtree(session_content_dir)

        # External documents — sibling vector store directory, if file-backed
        external_documents_dir = self._external_documents_directory()
        if external_documents_dir is not None:
            self._rmtree(external_documents_dir)

        # Per-user registry — a file, or a namespaced store
        reg_conn = self._registry_props.get("connection", self._registry_props)
        if "path" in reg_conn:
            self._unlink_store_file(reg_conn["path"])
        elif self._registry_props.get("namespace"):
            _build_json_source("registry", self._registry_props).delete(None)

        # The KB directory, last: in the default layout it also holds the JSON
        # stores and the vector directories removed above (#179). Left in place
        # if anything else is still in it.
        if user_dir is not None:
            with contextlib.suppress(OSError):
                user_dir.rmdir()
        return list(self._refused)

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

    def _ensure_session_source(self) -> Any:
        if self._session_source is not None:
            return self._session_source
        if self._registry is None:
            raise ValueError("Registry not ready — call build() or connect() first.")
        source = self._registry.connect_source("sessions")
        if source is None:
            raise ValueError(f"No 'sessions' source in registry for user {self._database!r}.")
        self._session_source = source
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
        # Endpoints resolve by exact name, never via search_schema: that is a
        # *ranked* match, and e.g. "PERSON" scores USER ("Digital user profile
        # extending PERSON") above PERSON itself, which seeds USER IS_SUBCLASS_OF
        # USER. Labels outside this mapping (PROPERTY subclassing, declared by
        # some schema files) are skipped — add_is_subclass_of takes CLASS or
        # RELATION nodes only.
        finders = {"CLASS": kb.find_class, "RELATION": kb.find_relation_type}
        for sc in schema_dict.get("subclasses", []):
            find_child = finders.get(sc["child_label"])
            find_parent = finders.get(sc["parent_label"])
            if find_child is None or find_parent is None:
                continue
            child = await find_child(self._database, sc["child"])
            parent = await find_parent(self._database, sc["parent"])
            if child and parent:
                await kb.add_is_subclass_of(self._database, child["id"], parent["id"])

    async def seed_user_entity(self) -> str:
        """Ensure the user has a self-entity in the KB by default — ``<database> ->
        IS_INSTANCE_OF -> USER`` (``USER`` is ``IS_SUBCLASS_OF PERSON`` per the base
        schema) — rather than leaving it to be created lazily whenever/if onboarding's
        name question is answered.

        Named after the database key as a placeholder (e.g. ``"alice"``); safe to call
        more than once (reuses the existing entity instead of creating a duplicate).
        :meth:`set_person_name` renames this same entity once the real name is known.
        """
        kb = self._ensure_kb_source()
        user_class = await kb.find_class(self._database, "USER")
        class_id = user_class["id"] if user_class else None

        entity = await kb.find_entity(self._database, self._database)
        if entity is not None:
            return entity["id"]
        return await kb.add_entity(self._database, self._database, class_id=class_id)

    async def execute_query(
        self,
        query: str,
        on_tool_call=None,
        on_tool_result=None,
        session_id: str | None = None,
        top_k: int = DOC_SEARCH_TOP_K,
    ) -> tuple[list[Any], dict[str, Any]]:
        """Answer *query* against the KB, session_content, and external_documents combined.

        ``top_k`` caps the chunks taken from each document store; the KB answers
        through its own agent and has no result limit.
        """
        result, metadata = await self._ensure_kb_source().answer(
            self._database, query,
            include_metadata=True,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
        )
        data = result if isinstance(result, list) else ([{"answer": result}] if result else [])
        metadata = metadata if isinstance(metadata, dict) else {}

        session_doc_source = self.ensure_session_doc_source(session_id or "")
        data.extend(
            self._search_doc_source(
                session_doc_source, query, "session_content", metadata, top_k,
            )
        )

        external_doc_source = self.ensure_external_documents_source()
        data.extend(
            self._search_doc_source(
                external_doc_source, query, "external_documents", metadata, top_k,
            )
        )

        logger.debug("Query executed: %s", query)
        return data, metadata

    def _search_doc_source(
        self, doc_source: Any, query: str, source_name: str, metadata: dict[str, Any],
        top_k: int = DOC_SEARCH_TOP_K,
    ) -> list[dict[str, Any]]:
        """Run DOCUMENT.SEARCH against *doc_source*, tagging each hit with *source_name*."""
        request = {"op": "DOCUMENT.SEARCH", "query": query, "k": top_k}
        chunks = doc_source.execute_query(request)
        entries: list[dict[str, Any]] = []
        for chunk in chunks:
            entries.append({
                "text": chunk.get("text"),
                "source": source_name,
                "file_name": chunk.get("file_name"),
                "score": chunk.get("score"),
            })
            metadata[chunk["chunk_id"]] = {"source": source_name, "extraction": chunk.get("text")}
        return entries

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
        effort: Literal["low", "medium", "high"] = "medium",
        location: str | None = None,
        text: str | None = None,
    ) -> None:
        """Register a file as a source, always ingesting it into the shared
        "external_documents" DocumentDataSource (parsed, chunked, embedded —
        see :meth:`ensure_external_documents_source`), and optionally also
        extracting facts into the KB for each of *queries* (Type 2 import).

        ``effort`` is how many times the extraction pipeline passes over the
        text (low/medium/high = 1/2/3); a single pass leaves much of a
        moderately dense document unextracted.

        Deliberately does NOT create a per-file record in the outer
        DataRegistry — only the shared "external_documents" source is
        registered there. Individual documents are tracked solely by that
        DocumentDataSource (KB SOURCE-node provenance is unaffected). See #95:
        once documents are properly tracked (#89), per-file discoverability
        (listing / removal) should be revisited.
        """
        kb = self._ensure_kb_source()
        # With ``text``, the document is that text and *source* is unused: no file
        # is read or written. ``location`` is what the SOURCE node records; it
        # defaults to the path read, or "text:<name>" for text (#151).
        path = None if text is not None else getattr(source, "location", str(source))
        location = location or path or f"text:{name or 'text'}"
        # The SOURCE node's description is rendered into the extraction system
        # prompt, so naming the owner here is what lets the extractor tie an
        # unattributed document ("Results-driven Project Manager with...") to
        # this user's own entity instead of inventing a second person for it.
        owner = self._owner_name()
        source_id = await kb.add_source(
            self._database, location, name=name,
            description=description or f"Belongs to {owner}, the user this knowledge base is about",
            original=original,
        )

        doc_source = self.ensure_external_documents_source()
        # No "collection" override — falls through to the pipeline's own
        # default_collection ("documents"), matching the index created by
        # ensure_external_documents_source().
        if text is not None:
            chunks = doc_source.ingest_text(text, file_name=f"{name or 'text'}.txt")
        else:
            chunks = doc_source.execute_query({"op": "DOCUMENT.INGEST", "path": path})
        if chunks:
            # The doc store can delete a document from another process only by
            # id + chunk count (its path index is per-process), so keep both,
            # keyed by the SOURCE node, for remove_source.
            self._registry.register_record(
                name=sanitize_registry_name(source_id), type=_DOCUMENT_RECORD, scope="/",
                description=f"external_documents chunks of {name or location}",
                properties={"document_id": chunks[0]["document_id"], "chunk_count": len(chunks)},
            )

        if queries:
            # Headings live in "section_title", not in the chunk body — a resume's
            # job titles, degree, and name header are all headings, so joining only
            # the bodies hands the extractor a document with those removed.
            body = "\n".join(
                f"{chunk['section_title']}\n{chunk['text']}" if chunk.get("section_title")
                else chunk["text"]
                for chunk in chunks
            )
            # A document often never names its own subject — a resume's name header is
            # consumed as the document title, and the prose is all first-person — which
            # leaves the extractor with no entity to hang WORKED_AT/HAS_SKILL facts on,
            # so it either invents a second person or skips the relations entirely.
            text = f"This document belongs to {owner}, the subject of every fact in it.\n{body}"
            await kb.import_text(
                self._database, text, queries=queries, source_id=source_id, effort=effort
            )

    async def remove_source(self, source_name: str) -> dict[str, Any]:
        """Remove a source added with :meth:`add_source`, by its name or id.

        Deletes its chunks from "external_documents", so it no longer reaches
        searches or query answers, and its KB SOURCE node with the extraction
        records under it. Facts extracted from it stay in the KB; only their
        link to this source goes. Raises ``QueryError`` when no source, or more
        than one, has that name.

        Returns ``{"id", "name", "chunks_removed"}``. ``chunks_removed`` is None
        for a source added before its document was recorded: its chunks cannot
        be located, and only a reset of the KB removes them.
        """
        from blue_data_user_source.types import QueryError

        matches = [s for s in await self.list_sources() if source_name in (s.get("id"), s.get("name"))]
        if not matches:
            raise QueryError(f"No source {source_name!r} for user {self._database!r}.")
        if len(matches) > 1:
            ids = ", ".join(str(s.get("id")) for s in matches)
            raise QueryError(
                f"{len(matches)} sources are named {source_name!r} for user {self._database!r}; "
                f"remove one by id ({ids})."
            )
        source_id = matches[0]["id"]

        chunks_removed: int | None = None
        record = self._registry.get_record(sanitize_registry_name(source_id), _DOCUMENT_RECORD)
        if record:
            props = record.get("properties") or {}
            self.ensure_external_documents_source().execute_query({
                "op": "DOCUMENT.DELETE",
                "document_id": props["document_id"],
                "chunk_count": props["chunk_count"],
            })
            chunks_removed = int(props["chunk_count"])
            self._registry.deregister(record)

        await self._ensure_kb_source().delete_source(self._database, source_id)
        return {"id": source_id, "name": matches[0].get("name"), "chunks_removed": chunks_removed}

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

    def _owner_name(self) -> str:
        """What text about this user calls them — their name once onboarding has set
        it, else the database key. Used to anchor extracted facts to the user's own
        entity; see :meth:`store_data` and :meth:`add_source`."""
        return self.get_metadata("identity.name") or self._database

    async def store_data(
        self,
        text: str,
        source_id: str | None = None,
        queries: list[str] | None = None,
    ) -> None:
        """Extract *text* — a user's own answer to a question — into the KB.

        The text is prefixed with a line naming the user, because on its own an
        answer names nobody: "Question: What is your nationality?\\nUser Response:
        USA" gives the extractor a second-person question and a bare country, so it
        records COUNTRY "USA" and has no person to hang PERSON.NATIONALITY on.
        """
        anchored = (
            f"The following question and answer are about {self._owner_name()}, "
            f"the user this knowledge base describes.\n{text}"
        )
        await self._ensure_kb_source().import_text(
            self._database, anchored, queries=queries, source_id=source_id
        )

    async def set_person_name(self, first_name: str, last_name: str | None = None) -> str:
        """Deterministically create/update the user's single USER entity (``IS_INSTANCE_OF
        USER``, which is ``IS_SUBCLASS_OF PERSON`` per the base schema).

        Labels the entity with the user's *full* name and stores ``first_name`` /
        ``last_name`` as FIRST_NAME/LAST_NAME properties on it via direct
        graph writes rather than LLM-based text extraction, so this always
        produces exactly one USER node. Safe to call more than once: reuses
        the existing entity (matched by name) instead of creating a duplicate.
        If a placeholder entity was already seeded by :meth:`seed_user_entity`
        (named after the database key), renames that same entity instead of
        creating a second one.

        The label is the full name because that is what documents about the
        user call them: extraction resolves candidates by exact name (with only
        a case/punctuation-insensitive fallback), so a first-name-only label
        leaves "Alice Chen" in a resume unmatched and forks a second person
        entity that the user's own facts then hang off.

        Returns the USER entity's id.
        """
        kb = self._ensure_kb_source()
        user_class = await kb.find_class(self._database, "USER")
        class_id = user_class["id"] if user_class else None
        label = f"{first_name} {last_name}" if last_name else first_name

        entity = await kb.find_entity(self._database, label)
        if entity is not None:
            entity_id = entity["id"]
        else:
            placeholder = await kb.find_entity(self._database, self._database)
            if placeholder is not None:
                await kb.update_entity(self._database, placeholder["id"], name=label)
                entity_id = placeholder["id"]
            else:
                entity_id = await kb.add_entity(self._database, label, class_id=class_id)

        for attr_name, value in (("FIRST_NAME", first_name), ("LAST_NAME", last_name)):
            if not value:
                continue
            prop = await kb.find_property(self._database, attr_name)
            if prop is not None:
                await kb.add_entity_property_value(
                    self._database, value, entity_id=entity_id, property_id=prop["id"]
                )
        return entity_id

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
            if get_path(meta, f"metadata.{category}") is None:
                meta.set(f"metadata.{category}", {})
            if entries.get("__open__"):
                continue
            for key, spec in entries.items():
                if key.startswith("__"):
                    continue
                dotted = f"metadata.{category}.{key}"
                if get_path(meta, dotted) is None:
                    meta.set(dotted, spec.get("default"))

    def clear_metadata(self) -> None:
        self._ensure_metadata_source().set("metadata", {})

    def get_metadata(self, key: str) -> Any:
        return get_path(self._ensure_metadata_source(), f"metadata.{key}")

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
            if get_path(store, f"contacts.{protocol}") is None:
                store.set(f"contacts.{protocol}", {})

    def clear_contacts(self) -> None:
        self._ensure_contact_source().set("contacts", {})

    def get_contact_source(self) -> Any:
        return self._ensure_contact_source()

    def get_contacts(self) -> dict[str, Any]:
        return self._ensure_contact_source().get("contacts") or {}

    # Contact protocol and name are validated like ContactManager does: both are
    # dot-path segments, and a dotted name addressed another contact's field (#142).
    # ``field`` may be dotted on purpose (e.g. ``headers.Authorization``).

    def get_contact(self, protocol: str, name: str) -> dict[str, Any] | None:
        from blue_data_user_source.interaction.contact import ContactManager

        path = ContactManager._path(protocol, name)
        return get_path(self._ensure_contact_source(), path) if path else None

    def set_contact_field(self, protocol: str, name: str, field: str, value: Any) -> None:
        from blue_data_user_source.interaction.contact import ContactManager
        from blue_data_user_source.types import InteractionError

        path = ContactManager._path(protocol, name)
        if path is None:
            raise InteractionError(f"Invalid contact {protocol!r}/{name!r}.")
        store = self._ensure_contact_source()
        if get_path(store, path) is None:
            store.set(path, {})
        store.set(f"{path}.{field}", value)

    def delete_contact(self, protocol: str, name: str) -> None:
        from blue_data_user_source.interaction.contact import ContactManager

        path = ContactManager._path(protocol, name)
        if path is not None:
            self._ensure_contact_source().delete(path)

    # ------------------------------------------------------------------ #
    # Session operations                                                   #
    # ------------------------------------------------------------------ #

    def clear_sessions(self) -> None:
        self._ensure_session_source().set("sessions", {})
        self._clear_session_content()

    def get_session_source(self) -> Any:
        return self._ensure_session_source()

    # ------------------------------------------------------------------ #
    # Session document source (per-session interaction transcripts)       #
    # ------------------------------------------------------------------ #

    def _session_vector_directory(self) -> Path | None:
        """Directory backing the session_content doc source's vector store, or ``None``.

        ``None`` when ``doc_source_props`` points the vector store at the
        in-memory backend (the default) — there's nothing durable to locate.
        """
        vector_props = self._doc_source_props.get("vector_source") or {"backend": "memory"}
        vector_enriched = _enrich_props(vector_props, "vector")
        directory = vector_enriched.get("connection", {}).get("directory")
        return Path(directory) if directory is not None else None

    def _external_documents_directory(self) -> Path | None:
        """Directory backing the external_documents doc source's vector store, or ``None``.

        A sibling of the session vector directory (e.g.
        ``.../sources/alice/external_documents`` next to ``.../sessions``) —
        see :meth:`ensure_external_documents_source`. ``None`` under the
        in-memory backend, same as :meth:`_session_vector_directory`.
        """
        session_directory = self._session_vector_directory()
        if session_directory is None:
            return None
        return session_directory.parent / "external_documents"

    def _session_transcripts_dir(self, session_id: str) -> Path | None:
        """Directory for raw interaction-transcript ``.txt`` files, or ``None``.

        Mirrors the persistence of the session's vector backend: when
        ``doc_source_props`` points the vector store at a "file" backend,
        transcripts are written next to it (under ``transcripts/{session_id}``)
        so both survive a process restart. When the vector backend is
        in-memory (the default), there's nothing durable to write to, so this
        returns ``None`` and callers should skip persisting the raw file.
        """
        directory = self._session_vector_directory()
        if directory is None:
            return None
        path = directory / "transcripts" / session_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _clear_session_content(self) -> None:
        """Remove persisted session_content vector data and raw transcript files.

        The vector store's file backend (e.g. ``documents.json``) and the
        ``transcripts/`` directory live outside the per-user registry, so
        clearing the "sessions" JSON record alone leaves them behind. No-op
        when the vector backend is in-memory — see :meth:`_session_vector_directory`.
        """
        recorded = self._session_vector_directory()
        directory = self._contained(recorded) if recorded is not None else None
        if directory is None or not directory.exists():
            return
        self._rmtree(directory / "transcripts")
        for path in directory.glob("*.json"):
            self._unlink(path)
        self._session_doc_source = None

    def _clear_external_documents(self) -> None:
        """Remove the persisted external_documents store (chunks of every added file).

        It lives outside the per-user registry, so deregistering its record
        leaves the files behind, and the next ``ensure_external_documents_source``
        reloads them. No-op when the vector backend is in-memory.
        """
        directory = self._external_documents_directory()
        if directory is not None:
            self._rmtree(directory)
        self._external_doc_source = None
        for record in self._registry.list_records(record_type=_DOCUMENT_RECORD, scope="/") or []:
            self._registry.deregister(record)

    def save_session_transcript(self, session_id: str, file_name: str, text: str) -> Path | None:
        """Persist raw interaction-transcript text as a ``.txt`` file on disk.

        No-op (returns ``None``) when the session's doc source uses an
        in-memory vector backend — see :meth:`_session_transcripts_dir`.
        """
        directory = self._session_transcripts_dir(session_id)
        if directory is None:
            return None
        file_path = directory / file_name
        file_path.write_text(text)
        return file_path

    def ensure_session_doc_source(self, session_id: str) -> Any:
        """Return the shared "session_content" DocumentDataSource, built + registered on first use.

        A single DocumentDataSource holds interaction transcripts for *all*
        sessions (one file per interaction, named ``{query_id}-{interaction_id}.txt``)
        rather than one source per session — *session_id* is accepted for a
        stable call signature but no longer affects the source's identity.

        Not reconnected via DataRegistry.connect_source — see class docstring.
        Cached per-process in self._session_doc_source; a fresh process rebuilds
        it (with a fresh, empty vector backend unless doc_source_props points at
        a persistent one, e.g. the "file" vector backend).
        """
        if self._session_doc_source is not None:
            return self._session_doc_source
        if self._registry is None:
            raise ValueError("Registry not ready — call build() or connect() first.")

        from blue_data_doc_source import DocumentDataSource

        name = "session_content"
        embedding_model = _build_embedding_model(self._doc_source_props.get("embedding_model"))
        vector_props = self._doc_source_props.get("vector_source") or {"backend": "memory"}
        vector_enriched = _enrich_props(vector_props, "vector")
        vector_conn = vector_enriched.get("connection", {})
        if "directory" in vector_conn:
            Path(vector_conn["directory"]).mkdir(parents=True, exist_ok=True)
        vector_source = DataSource.instantiate(
            vector_enriched["_class"], f"{name}-vectors", properties={"connection": vector_conn},
        )
        doc_source = DocumentDataSource(
            name=name, embedding_model=embedding_model, vector_source=vector_source,
        )
        # DOCUMENT.SEARCH's vector/hybrid modes look up the vector store's
        # index by name and find nothing if it was never created — ingest_text()
        # doesn't create it, so it must happen explicitly, once, up front (see
        # the matching comment in ensure_external_documents_source).
        doc_source.execute_query({"op": "DOCUMENT.ENSURE_INDEX"})
        self._registry.register_source(doc_source)
        self._session_doc_source = doc_source
        return doc_source

    def ensure_external_documents_source(self) -> Any:
        """Return the shared "external_documents" DocumentDataSource, built + registered on first use.

        Every file registered via :meth:`add_source` (``blue-userdb data source add``)
        is parsed, chunked, and embedded into this single DocumentDataSource,
        making it searchable and available for future query-answering —
        replacing the old FileSource, which only ever read raw lines.

        Uses the same ``doc_source_props`` (embedding model + vector backend)
        as :meth:`ensure_session_doc_source`, but — when file-backed — writes
        under its own sibling ``external_documents/`` directory (as
        ``documents.json`` + ``_indices.json``) rather than inside the
        "sessions" directory, which is reserved for session transcripts.

        Not reconnected via DataRegistry.connect_source — see class docstring.
        Cached per-process in self._external_doc_source; a fresh process
        rebuilds it (with a fresh, empty vector backend unless
        doc_source_props points at a persistent one, e.g. the "file" vector
        backend).
        """
        if self._external_doc_source is not None:
            return self._external_doc_source
        if self._registry is None:
            raise ValueError("Registry not ready — call build() or connect() first.")

        from blue_data_doc_source import DocumentDataSource

        name = "external_documents"
        collection = "documents"
        embedding_model = _build_embedding_model(self._doc_source_props.get("embedding_model"))
        vector_props = self._doc_source_props.get("vector_source") or {"backend": "memory"}
        vector_enriched = _enrich_props(vector_props, "vector")
        vector_conn = vector_enriched.get("connection", {})
        if "directory" in vector_conn:
            # The configured directory names the *sessions* vector store —
            # external_documents gets its own sibling directory instead of
            # sharing that one (see _external_documents_directory).
            directory = self._external_documents_directory()
            vector_conn = {**vector_conn, "directory": str(directory)}
            directory.mkdir(parents=True, exist_ok=True)
        vector_source = DataSource.instantiate(
            vector_enriched["_class"], f"{name}-vectors", properties={"connection": vector_conn},
        )
        doc_source = DocumentDataSource(
            name=name, embedding_model=embedding_model, vector_source=vector_source,
            default_collection=collection,
        )
        # DOCUMENT.SEARCH's vector/hybrid modes look up the vector store's
        # index by name and return nothing if it was never created — ingest()
        # doesn't create it, so it must happen explicitly, once, up front.
        doc_source.execute_query({"op": "DOCUMENT.ENSURE_INDEX", "collection": collection})
        self._registry.register_source(doc_source)
        self._external_doc_source = doc_source
        return doc_source
