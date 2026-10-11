# UDb — API / Interface Spec

All four external interfaces are thin adapters over the Python library. No business logic belongs in any interface layer. Authentication and authorization are mostly left to the deployment layer: the REST API offers an optional shared key and a cross-origin write guard (§2), and the MCP server runs over stdio, so it is only as exposed as the process that launches it.

This spec lists the contract and the design choices behind it; the user documentation ([docs/api-reference.md](../docs/api-reference.md), [docs/api.md](../docs/api.md), [docs/mcp.md](../docs/mcp.md), [docs/cli.md](../docs/cli.md)) has every parameter.

---

## 1. Python Library

The canonical interface. All other interfaces delegate to it.

### `UserSource`

```python
class UserSource(DataSource):

    # ---- database (= user) management ----

    def create_database(self, database: str, properties: dict | None = None) -> dict: ...
    # Sync DataSource override; delegates to create_user via asyncio.run().
    # properties must contain: registry, kb_source, metadata_source, contact_source,
    # session_source keys. doc_source is optional (defaults to a dummy-embedding,
    # in-memory vector backend — see Session Manager below).

    async def create_user(
        self,
        name: str,
        registry_props: dict,
        kb_source_props: dict,
        metadata_source_props: dict,
        contact_source_props: dict,
        session_source_props: dict,
        doc_source_props: dict | None = None,
        onboard: bool = True,            # ask the user a few questions after creating
        onboard_metadata: bool = True,
    ) -> None: ...

    async def onboard_user(self, name: str, ...) -> None: ...

    def list_users(self) -> list[str]: ...
    def get_user(self, name: str) -> dict | None: ...
    def remove_user(self, name: str) -> None: ...
    async def reset_user(self, name: str) -> None: ...
    async def delete_user(self, name: str) -> None: ...

    # ---- DataSource query interface (sync) ----

    def execute_query(
        self,
        query: str,
        database: str | None = None,
        collection: str | None = None,
        optional_properties: dict | None = None,
    ) -> tuple[Any, str]: ...
    # Returns (answer, session_id) — the session is the reused or newly-created
    # one this query landed in. See "Result shape" and "session" below.

    async def async_execute_query(
        self, query: str, database: str | None = None, optional_properties: dict | None = None,
    ) -> tuple[Any, str]: ...
    # The same call for async callers (the REST API and MCP server use it).

    def execute_query_nl(
        self,
        query: str,
        database: str | None = None,
        collection: str | None = None,
        optional_properties: dict | None = None,
    ) -> tuple[Any, str]: ...
    # Same as execute_query; the DataSource interface's NL entry point.

    # ---- sessions ----

    async def create_session(self, database: str) -> str: ...
    async def end_session(self, database: str, session_id: str) -> None: ...
    async def get_session(self, database: str, session_id: str) -> dict | None: ...
    async def list_sessions(self, database: str) -> dict[str, Any]: ...

    def import_data(
        self,
        source: Any,
        database: str = "default",
        collection: str = "default",
        entity: str | None = None,
        mode: str = "append",
        options: dict | None = None,
    ) -> dict: ...
    # Hands data straight to the knowledge graph (KBSource.import_data);
    # documents go through add_source / add_text_source.

    # ---- source management ----

    async def add_source(
        self,
        source: str | Path,          # a file path
        database: str,
        optional_properties: dict | None = None,
    ) -> None: ...

    async def add_text_source(
        self,
        text: str,                   # no file is read or written
        database: str,
        optional_properties: dict | None = None,
    ) -> None: ...

    async def remove_source(self, database: str, source_name: str) -> dict: ...

    # ---- data access ----

    async def list_data(self, database: str) -> list[dict]: ...
    async def describe_data(self, database: str, model: str | None = None) -> str: ...
    async def list_sources(self, database: str, source_id: str | None = None) -> list[dict]: ...
    async def describe_sources(self, database: str, source_id: str | None = None) -> str: ...

    def list_metadata(self, database: str) -> dict[str, Any]: ...
    def get_metadata(self, database: str, key: str) -> Any: ...
    def set_metadata(self, database: str, key: str, value: Any) -> None: ...
    def delete_metadata(self, database: str, key: str) -> None: ...

    # ---- contact methods ----

    async def add_contact_method(self, database: str, protocol: str, name: str,
                                 details: dict | None = None, preference: int = 0) -> None: ...
    async def get_contact_method(self, database: str, protocol: str, name: str) -> ContactMethod | None: ...
    async def update_contact_method(self, database: str, protocol: str, name: str, ...) -> None: ...
    async def remove_contact_method(self, database: str, protocol: str, name: str) -> None: ...
    async def list_contact_methods(self, database: str, ...) -> list[ContactMethod]: ...
```

### Constructor

```python
UserSource(name: str, props: dict | None = None)
```

`MemoryUserSource`, `FileUserSource` and `RedisUserSource` fill in the store configs for their backend; `FileUserSource` is what the CLI and servers use.

| prop | Type | Description |
|------|------|-------------|
| `registry` | `dict` | `JSONSource` config (`_class` + `connection`) for the outer user registry; in-memory by default |
| `schema` | `str` | Path to the KB `schema.json`; used when creating or resetting databases |
| `metadata_schema` | `str` | Path to the metadata schema (default `data/metadata_schema.json`) |
| `contact_schema` | `str` | Path to the contact schema (default `data/contact_schema.json`) |
| `console` | `bool` | Whether the user is at this process's console (default `True`); servers pass `False`, so clarification never asks on stdin/stdout |

Every store config is a `blue-data` source record: `{"_class": "<module.Class>", "connection": {...}}`.

```python
us = FileUserSource("blue-userdb", {"schema": "data/schema.json"})

# Create a database — five store configs required, doc_source optional
await us.create_user(
    "alice",
    registry_props={"_class": CLS_JSON_FILE, "connection": {"protocol": "json/file", "path": "~/.blue-userdb/registries/alice.json"}},
    kb_source_props={"_class": CLS_KB_FILE, "connection": {"protocol": "kb/file", "directory": "~/.blue-userdb/sources/alice"}},
    metadata_source_props=...,   # JSONSource configs, as for the registry
    contact_source_props=...,
    session_source_props=...,
    doc_source_props={"embedding_model": "dummy", "vector_source": {"backend": "file", "directory": "~/.blue-userdb/sources/alice/sessions"}},
    onboard=False,
)

# Type 1 — add a file for future queries
await us.add_source("~/resume.txt", database="alice")

# Type 2 — also extract and store structured data from it
await us.add_source(
    "~/resume.txt",
    database="alice",
    optional_properties={"queries": ["What skills does the user have?"]}
)

# Query (sync — wraps asyncio internally). Reuse-or-create: pass "session" to
# append to an existing session, omit it to auto-create a new one.
answer, session_id = us.execute_query(
    "jobs suitable for me",
    database="alice",
    optional_properties={"session": session_id},
)
```

### `optional_properties` keys

| Key | Type | Method | Description |
|-----|------|--------|-------------|
| `"session"` | `str` | `execute_query` | Session ID to append this query to (reused). Raises `SessionNotFoundError` if unknown or `SessionEndedError` if already ended (both are `QueryError`s). Omit to auto-create a new single-query session — reuse-or-create, see Session Manager (§04-detailed-architecture.md) |
| `"output_form"` | `"json"` \| `"nl"` | `execute_query` | `"json"` returns one aggregated table (a list of dicts); `"nl"` returns prose |
| `"include_expanded"` | `bool` | `execute_query` | When `True` (default `False`), also returns the per-sub-question queries and raw results alongside the synthesized answer, in the same `output_form`; the return shape becomes `{"result": ..., "expanded": ...}` |
| `"max_interaction_rounds"` | `int` | `execute_query` | Max clarification rounds when quality metrics fail (default: 3); the loop stops early once all metrics pass |
| `"model"` | `str` | `execute_query` | LLM model for this query (default `gpt-4o`) |
| `"top_k"` | `int` | `execute_query` | Accepted (the CLI's `data query --top-k` sends it) but not used in 1.0 |
| `"queries"` | `list[str]` | `add_source`, `add_text_source` | Extraction queries — drives Type 2 ingestion (one `KBSource.import_text` call with all of them) |
| `"name"`, `"description"`, `"original"`, `"location"` | `str` | `add_source`, `add_text_source` | Recorded on the source's KB SOURCE node; `original` is the source's own date, `location` defaults to the path (or `text:<name>`) |
| `"effort"` | `"low"` \| `"medium"` \| `"high"` | `add_source`, `add_text_source` | Extraction passes over the text: 1, 2 or 3 (default `medium`) |

### Result shape

`execute_query` answers the whole question, synthesized across every sub-question: one aggregated table (a list of dicts sharing a schema derived from the query) for `"json"`, or prose for `"nl"`. With `include_expanded=True` the answer becomes `{"result": answer, "expanded": ...}`, where `expanded` lists each sub-question with its raw results (`{"query", "results"}` dicts for `"json"`, a prose summary for `"nl"`).

```python
@dataclass
class QueryResult:
    query: str          # the sub-question answered
    results: list[Any]  # retrieved data for that question
```

`QueryResult` is the per-sub-question record behind `expanded`.

### Sessions

```python
session_id = await us.create_session("alice")

results, session_id = us.execute_query(
    "jobs suitable for me", database="alice",
    optional_properties={"session": session_id},
)
# further queries with the same session_id continue this session

record = await us.get_session("alice", session_id)
# {"created_at": ..., "ended_at": None, "status": "active",
#  "doc_source_name": "session_content", "queries": {...}}

sessions = await us.list_sessions("alice")   # dict[session_id, record]

await us.end_session("alice", session_id)    # further create_query calls raise
```

See §6 of [10-data-model.md](10-data-model.md) for the full session/query/interaction record schema.

### Exceptions

All exceptions inherit from `UDbError` (defined in `types.py`).

| Exception | Parent | Raised when |
|-----------|--------|-------------|
| `QueryError` | `UDbError` | Query or lookup cannot be processed |
| `UserNotFoundError` | `QueryError` | The named user does not exist |
| `UserExistsError` | `QueryError` | Creating a user that already exists |
| `SessionNotFoundError` | `QueryError`, `InteractionError` | Unknown session id |
| `SessionEndedError` | `QueryError`, `InteractionError` | Adding a query to an ended session |
| `ImportError` | `UDbError` | Adding a source fails (file not found, etc.) |
| `LLMError` | `UDbError` | The LLM cannot be reached or fails (auth, network, rate limit, timeout, unknown model) |
| `InteractionError` | `UDbError` | A contact method is invalid or the user cannot be reached |
| `ContactNotFoundError` | `InteractionError` | Unknown contact method |
| `InteractionTimeoutError` | `InteractionError` | No reply in time |
| `NoContactMethodError` | `InteractionError` | No contact method can reach the user |

Inside a query, an `InteractionError` does not fail the query: the clarification loop stops, the interaction record ends `failed` or `timeout`, and the retrieved data is returned (#138).

---

## 2. REST API

FastAPI application. Each route calls one library operation. All handlers are `async def`; blocking behavior on long-running queries is acceptable — callers are expected to hold the connection. The user is always in the path (`/{name}/...`); there is no server-side default database.

**Access.** When `BLUE_DATA_USER_SOURCE_API_KEY` is set, every route except `/health`, the email-reply form (`/interactions/{id}/respond`, where the interaction id acts as the token) and the inbound-email webhook requires it in `X-API-Key` (401 otherwise). State-changing requests from a browser origin other than the API's own (or one listed in `BLUE_DATA_USER_SOURCE_ALLOWED_ORIGINS`) are refused with 403 (#139).

**Routes in 1.0**

| Area | Routes |
|------|--------|
| Databases | `GET /databases`, `POST/GET/DELETE /databases/{name}`, `POST /databases/{name}/reset` |
| Query | `POST /{name}/query` |
| Data and sources | `GET /{name}/data`, `GET/POST /{name}/sources`, `DELETE /{name}/sources/{source_name}` |
| Metadata | `GET /{name}/metadata`, `GET/PUT/DELETE /{name}/metadata/{key}` |
| Contacts | `GET/POST /{name}/contacts`, `GET/PATCH/DELETE /{name}/contacts/{protocol}/{contact_name}` |
| Sessions | `GET/POST /{name}/sessions`, `GET /{name}/sessions/{session_id}`, `POST /{name}/sessions/{session_id}/end` |
| Replies | `POST /interactions/{interaction_id}/response` (webhook), `GET/POST /interactions/{interaction_id}/respond` (the HTML form an email links to), `POST /interactions/email/inbound` |
| Health | `GET /health` |

The routes most tied to the design follow.

### `POST /{name}/query`

Execute a natural language query.

**Request** (`application/json`)

```json
{
  "query": "jobs suitable for me",
  "output_form": "json",
  "session": "optional-session-id",
  "include_expanded": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | yes | Natural language query |
| `output_form` | string | no | `"json"` (default) or `"nl"` |
| `include_expanded` | bool | no | Also return each sub-question's raw results (see Result shape, §1) |
| `session` | string | no | Session ID to append this query to (reused; 404 if unknown, 409 if ended). Omitted → a new single-query session is auto-created — reuse-or-create, see Session Manager |

**Response `200 OK`** (`application/json`)

```json
{
  "database": "alice",
  "query": "jobs suitable for me",
  "results": [
    {"job_title": "Data Engineer", "reason": "Python, SQL and pipeline experience"},
    {"job_title": "Machine Learning Engineer", "reason": "machine learning projects"}
  ],
  "session_id": "1c1919ff-9881-4429-8c52-ab6abae6ff1a"
}
```

`results` is the synthesized answer — the aggregated table above for `"json"`, a string for `"nl"`, or `{"result", "expanded"}` with `include_expanded`. `session_id` is always present — the session that was reused, or the one just auto-created.

---

### Sessions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/{name}/sessions` | Create a new session |
| `GET` | `/{name}/sessions` | List sessions for a database |
| `GET` | `/{name}/sessions/{session_id}` | Get one session's queries and interactions |
| `POST` | `/{name}/sessions/{session_id}/end` | End a session |

`POST /{name}/sessions` → `201 Created`, `{"database": "alice", "session_id": "..."}`.

`GET /{name}/sessions/{session_id}` → `200 OK` with the full record (see §6 of [10-data-model.md](10-data-model.md)), or `404` if unknown.

`POST /{name}/sessions/{session_id}/end` → `200 OK`, `{"database": "alice", "session_id": "...", "ended": true}` (also for an already-ended session), or `404` if unknown.

---

### `POST /{name}/sources`

Add a source and optionally extract attributes from it.

> **1.0: text only.** The request carries the source's text, which the server ingests directly (`UserSource.add_text_source`): nothing in the request is read as a path on the server (#133), no file is written, and the source's location is recorded as `rest:<name>` (#151). File uploads (`multipart/form-data`, as originally specified here) and session sources are not implemented over REST; add files with the CLI (`blue-userdb data source add FILE`) or the MCP `add_source` tool. File uploads are tracked in #147.

**Request** (`application/json`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | string | yes | The text to add (non-empty) |
| `name` | string | no | Label for the source (default `"text"`) |
| `description` | string | no | Description |
| `original` | string | no | The source's own date |
| `queries` | string[] | no | Extraction queries (Type 2); omit for Type 1 |

**Response `201 Created`** — `{"database": "...", "added": true}`

---

### `DELETE /{name}/sources/{source_name}`

Remove a source by name or id: its chunks are deleted from `external_documents` and its KB SOURCE node is deleted; facts extracted from it are kept. `404` when no source, or more than one, matches.

| Param | Type | Description |
|-------|------|-------------|
| `name` | string | Database (user) |
| `source_name` | string | Source name or id to remove |

**Response `200 OK`** — `{"database", "id", "name", "chunks_removed"}`

---

### `POST /databases/{name}`

Create a new database. No request body (an empty `{}` is accepted); every store is a file-backend default derived from the server's data directory, and any other key is rejected with `422`. Accepting store configs over REST let a caller choose the class the server imports and the paths it later deletes (#134).

**Response `201 Created`**

```json
{ "database": "alice" }
```

---

### `GET /health`

Liveness check.

**Response `200 OK`**

```json
{ "status": "ok" }
```

---

### Error responses

Errors use FastAPI's envelope, `{"detail": "<message>"}` (for request-validation errors, `detail` is FastAPI's list of field errors).

| HTTP status | Condition |
|------------|-----------|
| 401 | Missing or wrong `X-API-Key`, when a key is configured |
| 403 | State-changing request from a disallowed browser origin |
| 404 | `UserNotFoundError`, `SessionNotFoundError`, `ContactNotFoundError`; unknown source |
| 409 | `UserExistsError`, `SessionEndedError` |
| 422 | Request validation; any other `UDbError` (`QueryError`, `InteractionError`, `ImportError`) |
| 502 | `LLMError` — the model behind the request failed |
| 500 | Unexpected failure |

One exception-handler table in `app.py` maps each library exception to its status, most specific class first. No error handling logic lives in route handlers.

---

## 3. MCP Server

Exposes 23 MCP tools over stdio (FastMCP, server name `blue-data-user`). Tool handlers are thin wrappers over the Python library; all business logic remains in the library. Every tool names the user in a `user` argument; there is no server-side default. Each tool returns JSON text; on failure, `{"error": "<message>"}`.

| Area | Tools |
|------|-------|
| Databases | `create_database`, `delete_database`, `reset_database`, `list_databases`, `get_database` |
| Query | `query` |
| Sessions | `session_start`, `session_end`, `get_session`, `list_sessions` |
| Sources and data | `add_source`, `remove_source`, `list_data`, `list_sources` |
| Metadata | `set_metadata`, `delete_metadata`, `get_metadata`, `list_metadata` |
| Contacts | `add_contact`, `update_contact`, `remove_contact`, `list_contacts`, `get_contact` |

The JSON below shows the design-era shape of the main tools; the 1.0 names and parameters are noted under each, and [docs/mcp.md](../docs/mcp.md) has every schema.

### Tool: `execute_query`

> **1.0:** named `query`, with parameters `user`, `question`, `output_form`, `session` and `include_expanded`. Returns `{"results": <answer>, "session_id": "..."}`, where the answer has the shape described in §1 (Result shape).

```json
{
  "name": "execute_query",
  "description": "Query a user database in natural language. Returns structured results for each sub-question resolved from the original query.",
  "inputSchema": {
    "type": "object",
    "required": ["query"],
    "properties": {
      "query": {
        "type": "string",
        "description": "Natural language query"
      },
      "database": {
        "type": "string",
        "description": "Database ID. Uses server default if omitted."
      },
      "session": {
        "type": "string",
        "description": "Session ID to append this query to (reused). Omit to auto-create a new single-query session — reuse-or-create."
      }
    }
  }
}
```

**Returns:** JSON text content — `{"results": ..., "session_id": "..."}`. `session_id` is the reused or newly-created session.

**On error:** `{"error": "<message>"}`.

---

### Tools: `session_start`, `session_end`, `get_session`, `list_sessions`

Thin wrappers over the Session Manager (see [04-detailed-architecture.md](04-detailed-architecture.md)):

| Tool | Params | Returns |
|------|--------|---------|
| `session_start` | `user` | `{"user": "...", "session_id": "..."}` |
| `session_end` | `user`, `session_id` | `{"user": "...", "session_id": "...", "ended": true}` |
| `get_session` | `user`, `session_id` | `{"session_id": "...", ...record fields, see §6 of 10-data-model.md}` |
| `list_sessions` | `user` | `dict[session_id, record]` |

Pass the `session_id` returned by `session_start` as the `session` argument to `execute_query` to continue that session across multiple calls.

---

### Tool: `add_source`

> **1.0:** parameters `user`, `source` (a file path on the server's machine), `name`, `description`, `original` and `queries`. Every source is ingested into `external_documents` (searchable at query time); `queries` add extraction into the KB.

```json
{
  "name": "add_source",
  "description": "Register a file as a data source for a user database. Omit queries to register only (Type 1). Provide queries to extract and store specific data from the file (Type 2).",
  "inputSchema": {
    "type": "object",
    "required": ["source_path"],
    "properties": {
      "source_path": {
        "type": "string",
        "description": "Filesystem path to the file to register"
      },
      "database": {
        "type": "string",
        "description": "Database ID. Uses server default if omitted."
      },
      "queries": {
        "type": "array",
        "items": { "type": "string" },
        "description": "Extraction queries for Type 2 ingestion. Omit for source registration only."
      }
    }
  }
}
```

**Returns:** a JSON confirmation on success; `{"error": "<message>"}` on failure.

---

### Tool: `remove_source`

> **1.0:** parameters `user` and `source_name`; returns `{database, id, name, chunks_removed}`.

```json
{
  "name": "remove_source",
  "description": "Remove a source: its document leaves search and query answers. KG facts extracted from the source are kept.",
  "inputSchema": {
    "type": "object",
    "required": ["source_name", "database"],
    "properties": {
      "source_name": {
        "type": "string",
        "description": "Name or id of the source to remove"
      },
      "database": {
        "type": "string",
        "description": "Database ID. Uses server default if omitted."
      }
    }
  }
}
```

**Returns:** see the 1.0 note above.

---

## 4. CLI

Built with Click (argument parsing) and Rich (output). All commands are thin wrappers over the Python library.

A default database may be configured via `--database` or the `BLUE_DATA_USER_SOURCE_DATABASE` env var, or persisted with `blue-userdb database select NAME`.

### Global options

```
blue-userdb [--version] [--profile NAME] [--database NAME] [--session ID] [--data-dir DIR]
            [--schema-path PATH] [--metadata-schema-path PATH] [--contact-schema-path PATH] COMMAND
```

Every option can also come from the selected profile (`blue-userdb profile`), which is how secrets such as `OPENAI_API_KEY` and the Neo4j password are supplied.

| Option | Env var | Default | Description |
|--------|---------|---------|-------------|
| `--database NAME` | `BLUE_DATA_USER_SOURCE_DATABASE` | — | Active database ID |
| `--data-dir DIR` | `BLUE_DATA_USER_SOURCE_DATA_DIR` | `~/.blue-userdb` | Directory for all database files |
| `--schema-path PATH` | `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | — | Path to `schema.json` for KB seeding |
| `--metadata-schema-path PATH` | `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` | — | Metadata schema for new databases |
| `--contact-schema-path PATH` | `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` | — | Contact schema for new databases |
| `--profile NAME` | — | selected profile | Configuration profile to use |
| `--session ID` | `BLUE_DATA_USER_SOURCE_SESSION` | — | Active session |

---

### `blue-userdb database`

| Command | Description |
|---------|-------------|
| `blue-userdb database create NAME` | Create a new database, and select it as active (auto-select-after-create) |
| `blue-userdb database delete NAME [--yes]` | Delete a database and all its data |
| `blue-userdb database select NAME` | Set the active database (persists to `.selected.database`) |
| `blue-userdb database list [--format]` | List all databases |
| `blue-userdb database search KEYWORD [--format]` | Keyword search over database names |
| `blue-userdb database reset [--yes]` | Clear KB data for the active database and reseed schema |
| `blue-userdb database config show [--format]` | Show stored configuration for the active database |
| `blue-userdb database onboard` | Run the onboarding interview for the active database |

`database create` options:

| Option | Default | Description |
|--------|---------|-------------|
| `--kb-backend` | `file` | KB backend: `memory`, `file`, or `neo4j` |
| `--neo4j-host` | `localhost` | Neo4j host (neo4j backend only) |
| `--neo4j-port` | `7687` | Neo4j bolt port |
| `--neo4j-user` | `neo4j` | Neo4j username |
| _(password)_ | — | Neo4j password (required for neo4j backend): the profile secret `BLUE_DATA_USER_SOURCE_NEO4J_PASSWORD` or that environment variable, never an option (ADR-026) |
| `--kb-search-mode`, `--kb-vector-backend`, `--kb-embedding-model` | — | Optional KB search index (keyword, semantic or both) |
| `--doc-backend` | `file` | Vector backend for per-session interaction transcripts: `memory` or `file` |
| `--onboard/--no-onboard`, `--metadata-onboard/--no-metadata-onboard` | on | Run the onboarding interview after creating (skipped without a terminal) |

---

### `blue-userdb session`

A session groups the queries/interactions of one conversation. Commands mirror `blue-userdb database`'s create/select/list pattern.

| Command | Description |
|---------|-------------|
| `blue-userdb session start` | Create a new session for the active database and select it (persists to `.selected.session`) |
| `blue-userdb session select SESSION_ID` | Set the active session |
| `blue-userdb session end [SESSION_ID]` | End a session (defaults to the selected session); clears the selection if it matches |
| `blue-userdb session list [--format]` | List sessions for the active database |
| `blue-userdb session show [SESSION_ID] [--format]` | Show a session's queries and interactions (defaults to the selected session) |

Session selection resolves the same way as `--database`: `--session` flag → `BLUE_DATA_USER_SOURCE_SESSION` env var → `.selected.session` file. **Unlike** database selection, an unresolved session is not an error — `blue-userdb data query` falls through to auto-creating a new session (reuse-or-create), and that new session is then auto-selected for the next call.

---

### `blue-userdb data`

All `data` commands require an active database.

| Command | Description |
|---------|-------------|
| `blue-userdb data query TEXT` | Execute a natural language query |
| `blue-userdb data search QUERY` | Search entities and facts by keyword or semantic similarity |
| `blue-userdb data list` | List all entities, property values, and facts |
| `blue-userdb data import FILE` | Import instance data from `blue-userdb data export` output (KG only) |
| `blue-userdb data export` | Export instance data (entities, facts, property values) as JSON |
| `blue-userdb data extract TEXT` | Extract entities/facts from free text via LLM |
| `blue-userdb data source list` | List sources (KG `SOURCE` nodes) with their ids |
| `blue-userdb data source add FILE` | Register a file source and optionally extract |
| `blue-userdb data source remove NAME` | Remove a source from the registry (KG data preserved) |

`data query` options:

| Option | Description |
|--------|-------------|
| `--session SESSION_ID` | Session to append this query to. Falls back to the selected session (see `blue-userdb session` above), then to auto-create if neither is set |
| `--format table\|json\|nl` | Output format (default: `table`) |
| `--top-k N` | Accepted but has no effect in 1.0 (the library ignores `top_k`) |
| `--include-expanded` | Also show each sub-question's raw results |
| `--model` | LLM model for this query |

When a query auto-creates a new session (no `--session`, no selected session), the CLI writes it to `.selected.session` so the next `blue-userdb data query` call continues the same session automatically.

**Example**

```
$ blue-userdb --database alice data query "jobs suitable for me" --format table

 Query                               Results
 What skills does the user have?     Python, SQL, machine learning
 Does the user prefer remote work?   Yes
```

`data source add` — two types:

```bash
# Type 1 — register source only
blue-userdb data source add resume.txt
# Registered source: resume.txt

# Type 2 — register + extract
blue-userdb data source add resume.txt \
  --query "What skills does the user have?" \
  --query "What is the user's most recent job title?"
# Added source: resume.txt (2 queries)
```

---

### `blue-userdb metadata`, `contact`, `profile`

| Command | Description |
|---------|-------------|
| `blue-userdb metadata list\|get\|set\|delete` | Read and write the user's metadata (identity, preferences, availability, privacy) by dotted key |
| `blue-userdb contact list\|get\|add\|set\|remove` | Manage contact methods; secret fields are masked on read |
| `blue-userdb profile list\|add\|select\|config\|inspect\|remove` | Manage configuration profiles |

---

### `blue-userdb schema`

All `schema` commands require an active database.

| Command | Description |
|---------|-------------|
| `blue-userdb schema list [--format]` | List classes, relations, and their properties |
| `blue-userdb schema import FILE` | Import a schema (idempotent) |
| `blue-userdb schema export [-o FILE]` | Export schema as JSON |
| `blue-userdb schema search QUERY` | Search schema elements by keyword or semantic similarity |

---

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | `UDbError` — message printed via Rich to stderr |
| 2 | Bad arguments (Click default) |
