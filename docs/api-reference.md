# API Reference

Full method-by-method reference for the Python library. For a task-oriented introduction, see [guide.md](guide.md). For the design rationale behind the shapes described here, see [`design/09-api-interface-spec.md`](../design/09-api-interface-spec.md), which this page is kept in sync with.

> **Platform docs:** for the CLI command reference see [cli.md](cli.md); for the MCP tool reference see [mcp.md](mcp.md); for the REST API see [api.md](api.md).

---

## `UserSource`

```python
from blue_data_user_source import UserSource, FileUserSource, MemoryUserSource, RedisUserSource
```

Abstract base class over the outer user registry's storage. Three ready-made backends ship alongside it — `MemoryUserSource`, `FileUserSource`, and `RedisUserSource` — each mixing in a different `blue-data` `JSONSource` for the registry. See [architecture.md](architecture.md#backends) and [extending.md](extending.md) for building a new one.

```python
UserSource(name: str = "user_source", properties: dict | None = None)
```

`properties["registry"]` is a `JSONSource` config (`_class` + `connection`) for the outer registry's backing store; each subclass fills this in automatically from `properties["connection"]` if omitted (e.g. `FileUserSource` derives it from `connection.path`).

`properties["console"]` (default `True`) says whether the user is at this process's console. Servers pass `False` — the REST and MCP servers do — so clarification and onboarding never ask on stdin/stdout: console methods (`stdio`, and `email` with `inbound_provider: "stdio"`) are never selected, and when no other method can reach the user, a query returns what it retrieved without asking and onboarding is skipped. It describes the running process, so it is not stored in the registry; read it back as `UserSource.console`.

### Database (user) management

| Method | Returns | Description |
|---|---|---|
| `create_database(database, properties=None)` | `dict` | Sync `DataSource` override; delegates to `create_user` via `asyncio.run()` |
| `await create_user(name, registry_props, kb_source_props, metadata_source_props, contact_source_props, session_source_props, doc_source_props=None)` | `None` | Build a new user's `DataRegistry` + all built-in sources from scratch, seed schemas |
| `list_users()` | `list[str]` | Registered user names |
| `get_user(name)` | `dict \| None` | The user's registry properties dict, or `None` |
| `remove_user(name)` | `None` | Remove from the outer registry only — backing files unchanged |
| `await reset_user(name)` | `None` | Clear KB data + imported sources for the user, reseed schemas |
| `await delete_user(name)` | `None` | Destroy the user's stored data — backing files, and namespaced stores such as Redis keys — and remove it from the outer registry. A non-file store without its own `namespace` is left alone (it may be shared) and a warning is logged |

### Query

| Method | Returns | Description |
|---|---|---|
| `execute_query(query, database=None, collection=None, optional_properties=None)` | `tuple[list[QueryResult] \| str, str]` | Sync wrapper (`asyncio.run` internally); returns `(results, session_id)` |
| `execute_query_nl(query, database=None, collection=None, optional_properties=None)` | `tuple[list[QueryResult] \| str, str]` | Alias — identical behavior |
| `await async_execute_query(query, database=None, collection=None, optional_properties=None)` | `tuple[list[QueryResult] \| str, str]` | The `async` form both sync wrappers call |

`optional_properties`:

| Key | Type | Description |
|---|---|---|
| `session` | `str` | Session to append this query to (reused). Raises `QueryError` if unknown or ended. Omit to auto-create a new single-query session |
| `output_form` | `"json"` \| `"nl"` | `"json"` (default) → `list[QueryResult]`; `"nl"` → synthesized string |
| `include_expanded` | `bool` | Also return per-sub-question queries/results alongside the synthesized answer; shape becomes `{"result": ..., "expanded": ...}` |
| `max_interaction_rounds` | `int` | Max clarification rounds when quality metrics fail (default 3) |
| `top_k` | `int` | Max chunks taken from each document store (`external_documents`, `session_content`) per sub-question (default 5); the knowledge graph has no result limit |

### Sessions

| Method | Returns | Description |
|---|---|---|
| `await create_session(database)` | `str` | Create a new session; returns `session_id` |
| `await get_session(database, session_id)` | `dict \| None` | The session's record (queries + interactions) |
| `await list_sessions(database)` | `dict[str, Any]` | `dict[session_id, record]` |
| `await end_session(database, session_id)` | `None` | Mark `"ended"`; further `create_query` calls against it raise |

### Source management

| Method | Returns | Description |
|---|---|---|
| `await add_source(source, database, optional_properties=None)` | `None` | Register a source; `optional_properties["queries"]` drives Type 2 extraction |
| `await add_text_source(text, database, optional_properties=None)` | `None` | Add text as a source without a file (nothing is read or written on disk); same properties, `location` defaults to `"text:<name>"`. The REST API uses it |
| `await remove_source(database, source_name)` | `dict` | Remove a source by name or id: its document leaves search and query answers; facts extracted from it are kept. Returns `{id, name, chunks_removed}`; raises `QueryError` if no source, or more than one, matches |
| `await import_data(source, collection, database="default", entity=None, mode="append", options=None)` | `dict` | Lower-level `KBSource.import_data` passthrough |

`add_source`'s `optional_properties`:

| Key | Type | Description |
|---|---|---|
| `queries` | `list[str]` | Extraction queries — one `import_text` call each (Type 2) |
| `name` | `str` | Human-readable label |
| `description` | `str` | Optional description |
| `original` | `str` | Original publication date or provenance note |
| `location` | `str` | Label recorded as the source's location (default: the file's path, or `"text:<name>"` for a text source) |

### Data access

| Method | Returns | Description |
|---|---|---|
| `await list_data(database)` | `list[dict]` | Raw data entries from the KB |
| `await describe_data(database)` | `str` | Natural-language summary of KB data |
| `await list_sources(database, source_id=None)` | `list[dict]` | KB `SOURCE` nodes, optionally filtered |
| `await describe_sources(database, source_id=None)` | `str` | Natural-language summary of sources |

### Metadata

| Method | Returns | Description |
|---|---|---|
| `list_metadata(database)` | `dict[str, Any]` | Full metadata dict |
| `get_metadata(database, key)` | `Any` | Single value at a dot-separated key |
| `set_metadata(database, key, value)` | `None` | Set a value |
| `delete_metadata(database, key)` | `None` | Delete a key |

### Contact methods

| Method | Returns | Description |
|---|---|---|
| `await add_contact_method(database, protocol, name, details, preference=0)` | `None` | Create a contact method |
| `await get_contact_method(database, protocol, name)` | `ContactMethod \| None` | Fetch one |
| `await update_contact_method(database, protocol, name, details=None, preference=None, **fields)` | `None` | `details` replaces the stored fields (the preference is kept unless given); a secret field sent back masked as `***` keeps its stored value; `fields` set individual fields |
| `await remove_contact_method(database, protocol, name)` | `None` | Delete |
| `await list_contact_methods(database, protocol=None)` | `list[ContactMethod]` | All methods, optionally filtered by protocol |

---

## `UserQueryReasoner`

```python
UserQueryReasoner(source, manager=None, session_id=None, query_id=None)
```

Encapsulates query rewriting, metric-based assessment, and the interaction loop for one `execute_query` call. Instantiated with `_DEFAULT_METRICS` (`CompletenessMetric`, `FreshnessMetric`); appends `PrivacyMetric(manager=manager)` when a `manager` is given.

| Method | Returns | Description |
|---|---|---|
| `await contextualize_query(query)` | `str` | Rewrite the query, replacing self-references to the user with their actual name (`identity.name`, falling back to the database id) |
| `await expand_query(query)` | `list[str]` | Decompose into standalone, schema-grounded, third-person sub-questions (0–5) |
| `await assess_query_results(query, query_results, query_results_metadata)` | `list[MetricEvaluation]` | Evaluate all applicable metrics in parallel |
| `await assess_user_interaction(query, query_results, query_results_metadata, evaluations)` | `bool` | Whether any metric failed (also prints a per-metric line) |
| `await request_user_interaction(query, data, metadata, metrics, topic=None)` | `tuple[list, dict]` | Pick a contact method, ask one clarification question, record and return the augmented result |
| `await resolve_via_interaction(query, assessment_query, data, metadata, max_rounds=3, topic=None)` | `list[Any]` | Owns the full assess → interact → reassess cycle; returns only the newly collected responses |

---

## `UserDataMetric`

```python
from blue_data_user_source.reasoning.metric import (
    UserDataMetric, CompletenessMetric, FreshnessMetric, PrivacyMetric, MetricEvaluation,
)
```

Base class for one quality dimension. `THRESHOLD: float = 0.6` (class attribute); `_threshold()` returns it by default and can be overridden per-instance state.

| Method | Returns | Description |
|---|---|---|
| `await evaluate(query, query_results, query_results_metadata)` | `MetricEvaluation` | Score + reasoning + pass/fail for this dimension |

| Subclass | Notes |
|---|---|
| `CompletenessMetric` | Is enough information present to answer the query? |
| `FreshnessMetric` | Is the retrieved information recent enough? |
| `PrivacyMetric(manager)` | `_threshold()` moves with `privacy.consent_level`: 0.8 at `minimal`, 0.4 at `full`, 0.6 (default) otherwise |

```python
@dataclass
class MetricEvaluation:
    name: str
    score: float
    reasoning: str
    passes: bool
```

---

## `UserDataManager`

```python
UserDataManager(database: str, registry_props: dict, doc_source_props: dict | None = None)
```

Owns one user's `DataRegistry` and its five built-in sources (`kb`, `metadata`, `contacts`, `sessions`, plus the shared `session_content`/`external_documents` document stores).

| Method | Returns | Description |
|---|---|---|
| `await build(schema_path, kb_source_props, metadata_schema_path, metadata_source_props, contact_schema_path, contact_source_props, session_source_props)` | `None` | Create the registry, instantiate + register all sources, seed schemas — used for a brand-new user |
| `connect()` | `None` | Load an existing registry; sources reconnect lazily |
| `await reset(schema_path=None, metadata_schema_path=None, contact_schema_path=None, sources=None)` | `None` | Clear and reseed selected sources (default: `kb`, `metadata`, `contacts`, `sessions`) |
| `destroy()` | `None` | Delete all backing files, if file-backed |
| `await execute_query(query, on_tool_call=None, on_tool_result=None, session_id=None)` | `tuple[list, dict]` | Answer against `kb`, then merge top-`5` `DOCUMENT.SEARCH` hits from `session_content` and `external_documents`, each tagged `"source"` |
| `await add_source(source, queries=None, name=None, description=None, original=None)` | `None` | Ingest into `external_documents`; optionally run one `import_text` per query |
| `await remove_source(source_name)` | `dict` | Delete the source's `external_documents` chunks and its KB SOURCE node (facts kept); `chunks_removed` is `None` for a source added before documents were recorded |
| `await list_data()` | `list[dict]` | Raw KB data entries |
| `await list_sources(source_id=None)` | `list[dict]` | KB `SOURCE` nodes |
| `await store_data(text, queries=None)` | — | Store free text (used internally to persist interaction responses) |
| `get_metadata(key)` / `set_metadata(key, value)` / `delete_metadata(key)` / `list_metadata()` | | Dotted-path CRUD on the `metadata` source |
| `get_contacts()` / `get_contact(protocol, name)` / `set_contact_field(protocol, name, field, value)` / `delete_contact(protocol, name)` | | Dotted-path CRUD on the `contacts` source |
| `ensure_session_doc_source(session_id)` | `DocumentDataSource` | Get-or-create the shared `session_content` store |
| `ensure_external_documents_source()` | `DocumentDataSource` | Get-or-create the shared `external_documents` store |
| `save_session_transcript(session_id, file_name, text)` | `Path \| None` | Write a raw `.txt` transcript when the doc store's vector backend is file-based |

`sanitize_registry_name(name)` (module-level, re-exported from the package root) strips `/`, `\`, and `.` from a proposed registry record name — dotted-path stores would otherwise silently misinterpret those characters as nesting.

---

## `UserDataPlanner`

```python
UserDataPlanner(registry: DataRegistry)
```

| Method | Returns | Description |
|---|---|---|
| `await plan(query)` | `list[SubqueryPlan]` | One `SubqueryPlan(query, source)` per source registered in the registry — the query is not decomposed |

Not used by the query path in 1.0: `plan` returns the query unchanged, once per registered source, and `UserSource` never calls it. Query decomposition is done by `UserQueryReasoner.expand_query` (LLM sub-questions), and every sub-question is answered from the same fixed set of stores. Real source selection is future work (#128).

---

## `ContactManager` / `ContactMethod`

```python
ContactManager(database: str, data_manager: UserDataManager, console: bool = True)
```

| Method | Returns | Description |
|---|---|---|
| `await create_contact_method(protocol, name, details, preference=0)` | `None` | Create a named entry |
| `await get_contact_method(protocol, name)` | `ContactMethod \| None` | Fetch one |
| `await update_contact_method(protocol, name, details=None, preference=None, **fields)` | `None` | `details` replaces the stored fields (the preference is kept unless given); a secret field sent back masked as `***` keeps its stored value; `fields` set individual fields |
| `await delete_contact_method(protocol, name)` | `None` | Remove |
| `await list_contact_methods(protocol=None)` | `list[ContactMethod]` | All methods, optionally filtered |
| `await list_protocols()` | `list[str]` | Distinct protocols with at least one entry |
| `await list_named_entries(protocol)` | `dict[str, dict]` | All entries under one protocol |
| `await identify_contact_method(topic=None)` | `ContactMethod \| None` | Among methods with a transport (`stdio`, `email`, `webhook`): the sole one, or an LLM choice — see [architecture.md](architecture.md#interaction-layer). With none: `stdio` when there is a console, else `None` |

```python
ContactMethod(protocol: str, name: str, details: dict[str, Any])
```

| Member | Description |
|---|---|
| `preference` (property) | `int` — lower is preferred |
| `is_async` (property) | `bool` — `True` for `email`/`webhook`/`notification` |
| `interact(interaction_id=None)` | Returns an `InteractionManager` configured for this method's protocol (`stdio`, `webhook`, `email` — the latter branching on `inbound_provider` between a stdio-dev path and a real SMTP/inbound-webhook path) |

---

## `SessionManager`

```python
SessionManager(database: str, data_manager: UserDataManager)
```

| Method | Returns | Description |
|---|---|---|
| `await create_session()` | `str` | New session id |
| `await get_session(session_id)` | `dict \| None` | The session's record |
| `await list_sessions()` | `dict[str, Any]` | `dict[session_id, record]` |
| `await end_session(session_id)` | `None` | Mark `"ended"` |
| `await create_query(session_id, query, output_form="json")` | `str` | New query id under a session |
| `await create_interaction(session_id, query_id, question, protocol, name)` | `str` | New interaction id, status `"pending"` |
| `await resolve_interaction(session_id, query_id, interaction_id, response)` | `None` | Mark `"resolved"`, store the response |
| `await mark_interaction_timeout(session_id, query_id, interaction_id)` | `None` | Mark `"timeout"` |
| `await mark_interaction_failed(session_id, query_id, interaction_id, error)` | `None` | Mark `"failed"`, with the reason in `error` |

See [10-data-model.md](../design/10-data-model.md) §6 for the full session/query/interaction record schema.

---

## `InteractionManager`

```python
InteractionManager(on_start, on_response, on_stop)
```

| Method | Description |
|---|---|
| `await start()` | Calls `on_start()` |
| `await stop()` | Calls `on_stop()` |
| `await send(message, blocking=True)` | Sends a message; `blocking=True` awaits and returns the response directly |

---

## Result types

```python
from blue_data_user_source import QueryResult
```

```python
@dataclass
class QueryResult:
    query: str                    # the sub-question answered
    results: list[Any] = field(default_factory=list)
```

---

## Exceptions

```python
from blue_data_user_source import UDbError, QueryError, ImportError, InteractionError, NoContactMethodError, LLMError
```

All inherit from `UDbError`.

| Exception | Raised when |
|---|---|
| `QueryError` | A query cannot be processed, or no database/data manager is available |
| `ImportError` | A source import fails |
| `InteractionError` | User interaction fails (channel unavailable, timeout, etc.) |
| `LLMError` | The language model cannot be reached (authentication, network, rate limit, timeout, unknown model — any OpenAI SDK error), the `openai` package is missing, or a JSON-mode reply is not a JSON object. Raised rather than returning an empty result; the REST API maps it to `502` |
| `UserNotFoundError` / `UserExistsError` | `QueryError` subclasses: the named user does not exist / already exists |
| `SessionNotFoundError` / `SessionEndedError` | The named session does not exist / has ended (both are `QueryError` and `InteractionError`) |
| `ContactNotFoundError` | `InteractionError` subclass: the named contact method does not exist |
| `InteractionTimeoutError` | `InteractionError` subclass: the user did not answer within the contact's timeout |
| `NoContactMethodError` | Subclass of `InteractionError`: no contact method can reach the user from this process (no console, and nothing else registered). The query path catches it and answers without asking |

`ImportError` shadows the Python builtin within this package's namespace (`# noqa: A001` in `types.py`) — import it explicitly from `blue_data_user_source` rather than relying on it resolving to the builtin.
