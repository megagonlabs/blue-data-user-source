# UDb — API / Interface Spec

All four external interfaces are thin adapters over the Python library. No business logic belongs in any interface layer. Authentication and authorization are left to the deployment layer.

---

## 1. Python Library

The canonical interface. All other interfaces delegate to it.

### `UserSource`

```python
class UserSource(DataSource):

    # ---- database (= user) management ----

    def create_database(self, database: str, properties: dict | None = None) -> dict: ...
    # Sync DataSource override; delegates to create_user via asyncio.run().
    # properties must contain: registry, kb_source, metadata_source, contact_source keys.

    async def create_user(
        self,
        name: str,
        registry_props: dict,
        kb_source_props: dict,
        metadata_source_props: dict,
        contact_source_props: dict,
    ) -> None: ...

    def add_user(self, name: str, registry_props: dict) -> None: ...

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
    ) -> list[QueryResult]: ...

    def execute_query_nl(
        self,
        query: str,
        database: str | None = None,
        collection: str | None = None,
        optional_properties: dict | None = None,
    ) -> list[QueryResult]: ...

    def import_data(
        self,
        source: DataSource,
        collection: str,
        database: str = "default",
        entity: str | None = None,
        mode: str = "append",
        options: dict | None = None,
    ) -> dict: ...

    # ---- source management ----

    async def add_source(
        self,
        source: DataSource,
        database: str,
        optional_properties: dict | None = None,
    ) -> None: ...

    def remove_source(self, database: str, source_name: str) -> None: ...

    # ---- data access ----

    async def list_data(self, database: str) -> list[dict]: ...
    async def describe_data(self, database: str) -> str: ...
    async def list_sources(self, database: str, source_id: str | None = None) -> list[dict]: ...
    async def describe_sources(self, database: str, source_id: str | None = None) -> str: ...

    def list_metadata(self, database: str) -> dict[str, Any]: ...
    def get_metadata(self, database: str, key: str) -> Any: ...
    def set_metadata(self, database: str, key: str, value: Any) -> None: ...
    def delete_metadata(self, database: str, key: str) -> None: ...
```

### Constructor

```python
UserSource(props: dict)
```

| prop | Type | Description |
|------|------|-------------|
| `store` | `dict` | JSONSource config for the user-list store |
| `schema` | `str` | Default path to `schema.json`; used when creating or resetting databases |

```python
us = UserSource({
    "store": {"backend": "file", "path": "~/.udb/db.json"},
    "schema": "data/schema.json",
})

# Create a database — all four source props required
await us.create_user(
    "alice",
    registry_props={"backend": "file", "path": "~/.udb/registries/alice.json"},
    kb_source_props={"backend": "file", "directory": "~/.udb/kb"},
    metadata_source_props={"backend": "file", "path": "~/.udb/sources/alice.metadata.json"},
    contact_source_props={"backend": "file", "path": "~/.udb/sources/alice.contacts.json"},
)

# Type 1 — register file source for future queries
await us.add_source(FileSource("~/resume.txt"), database="alice")

# Type 2 — extract and store structured data from file
await us.add_source(
    FileSource("~/resume.txt"),
    database="alice",
    optional_properties={"queries": ["What skills does the user have?"]}
)

# Query (sync — wraps asyncio internally)
results = us.execute_query(
    "jobs suitable for me",
    database="alice",
    optional_properties={"session": session.cid}
)
```

### `optional_properties` keys

| Key | Type | Method | Description |
|-----|------|--------|-------------|
| `"session"` | `str` | `execute_query` | Session ID; used as query context and primary contact channel for user interaction |
| `"output_form"` | `"json"` \| `"nl"` | `execute_query` | `"json"` returns `list[QueryResult]`; `"nl"` returns a synthesized string |
| `"top_k"` | `int` | `execute_query` | Max KB results per sub-query (default: 10) |
| `"queries"` | `list[str]` | `add_source` | Extraction queries — drives Type 2 ingestion (one `import_text` call each) |

### Result type

```python
@dataclass
class QueryResult:
    query: str          # the sub-question answered
    results: list[Any]  # retrieved data for that question
```

`execute_query` returns one `QueryResult` per resolved sub-question.

### Exceptions

All exceptions inherit from `UDbError` (defined in `types.py`).

| Exception | Raised when |
|-----------|-------------|
| `QueryError` | Query cannot be processed or no database is available |
| `ImportError` | Import fails (file not found, source registration error, etc.) |
| `InteractionError` | User interaction fails (channel unavailable, timeout, etc.) |

---

## 2. REST API

FastAPI application. Endpoints map 1:1 to Python library operations. All handlers are `async def`; blocking behavior on long-running queries is acceptable — callers are expected to hold the connection.

A default database may be configured server-side at startup; when configured, the `database` field in request bodies is optional.

### `POST /query`

Execute a natural language query.

**Request** (`application/json`)

```json
{
  "query": "jobs suitable for me",
  "database": "alice",
  "session": "optional-session-id"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | yes | Natural language query |
| `database` | string | no | Database ID; uses server default if omitted |
| `session` | string | no | Session ID for query context and user interaction |

**Response `200 OK`** (`application/json`)

```json
{
  "results": [
    {
      "query": "What skills does the user have?",
      "results": ["Python", "SQL", "machine learning"]
    },
    {
      "query": "Does the user prefer remote work?",
      "results": [true]
    }
  ]
}
```

---

### `POST /sources`

Register a file source or extract data from it.

#### File source (`multipart/form-data`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | file | yes | File to add as source |
| `database` | string | no | Database ID; uses server default if omitted |
| `queries` | string (JSON array) | no | Extraction queries (Type 2); omit for Type 1 |

```
POST /sources
Content-Type: multipart/form-data

file=<binary>
database=alice
queries=["What skills does the user have?"]
```

#### Session source (`application/json`)

```json
{
  "source_type": "session",
  "source_id": "session-id",
  "database": "alice"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_type` | `"session"` | yes | Identifies a session source |
| `source_id` | string | yes | Session ID to register |
| `database` | string | no | Database ID; uses server default if omitted |

**Response `204 No Content`** (both shapes)

---

### `DELETE /sources/{source_name}`

Remove a source from the DataRegistry. KG data is preserved.

| Param | Type | Description |
|-------|------|-------------|
| `source_name` | string | Source name to remove |
| `database` | string (query) | Database ID |

**Response `204 No Content`**

---

### `POST /databases`

Create a new database.

**Request** (`application/json`)

```json
{
  "name": "alice",
  "registry": {"backend": "file", "path": "..."},
  "kb_source": {"backend": "file", "directory": "..."},
  "metadata_source": {"backend": "file", "path": "..."},
  "contact_source": {"backend": "file", "path": "..."}
}
```

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

All errors use a consistent envelope:

```json
{
  "error": {
    "code": "query_error",
    "message": "No database specified and no default configured."
  }
}
```

| HTTP status | `code` | Condition |
|------------|--------|-----------|
| 400 | `invalid_request` | Malformed request body |
| 404 | `database_not_found` | Specified database does not exist |
| 422 | `query_error` | Query could not be processed |
| 422 | `import_error` | Import failed |
| 500 | `internal_error` | Unexpected failure |

FastAPI exception handlers catch `UDbError` subtypes and map them to these responses. No error handling logic lives in route handlers.

---

## 3. MCP Server

Exposes three MCP tools. Tool handlers are thin wrappers over the Python library; all business logic remains in the library. A default database may be configured at server startup.

### Tool: `execute_query`

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
        "description": "Active session ID. Used as query context and as the primary contact channel when user interaction is required."
      }
    }
  }
}
```

**Returns:** JSON text content — array of `{"query": "...", "results": [...]}` objects, one per resolved sub-question.

**On error:** structured MCP error content containing the `UDbError` message.

---

### Tool: `add_source`

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

**Returns:** empty content on success. Structured MCP error content on failure.

---

### Tool: `remove_source`

```json
{
  "name": "remove_source",
  "description": "Remove a source from the user's DataRegistry. KG data extracted from the source is preserved.",
  "inputSchema": {
    "type": "object",
    "required": ["source_name", "database"],
    "properties": {
      "source_name": {
        "type": "string",
        "description": "Name of the source to remove from the registry"
      },
      "database": {
        "type": "string",
        "description": "Database ID. Uses server default if omitted."
      }
    }
  }
}
```

**Returns:** empty content on success.

---

## 4. CLI

Built with Click (argument parsing) and Rich (output). All commands are thin wrappers over the Python library.

A default database may be configured via `--database` or the `BLUE_DATA_USER_SOURCE_DATABASE` env var, or persisted with `udb database select NAME`.

### Global options

```
udb [--database NAME] [--data-dir DIR] [--schema-path PATH] COMMAND
```

| Option | Env var | Default | Description |
|--------|---------|---------|-------------|
| `--database NAME` | `BLUE_DATA_USER_SOURCE_DATABASE` | — | Active database ID |
| `--data-dir DIR` | `BLUE_DATA_USER_SOURCE_DATA_DIR` | `~/.udb` | Directory for all database files |
| `--schema-path PATH` | `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | — | Path to `schema.json` for KB seeding |

---

### `udb database`

| Command | Description |
|---------|-------------|
| `udb database create NAME` | Create a new database |
| `udb database delete NAME [--yes]` | Delete a database and all its data |
| `udb database select NAME` | Set the active database (persists to `.selected.database`) |
| `udb database list [--format]` | List all databases |
| `udb database search KEYWORD [--format]` | Keyword search over database names |
| `udb database reset [--yes]` | Clear KB data for the active database and reseed schema |
| `udb database config show [--format]` | Show stored configuration for the active database |

`database create` options:

| Option | Default | Description |
|--------|---------|-------------|
| `--kb-backend` | `file` | KB backend: `memory`, `file`, or `neo4j` |
| `--neo4j-uri` | — | Neo4j bolt URI |
| `--neo4j-user` | — | Neo4j username |
| `--neo4j-password` | — | Neo4j password |

---

### `udb data`

All `data` commands require an active database.

| Command | Description |
|---------|-------------|
| `udb data query TEXT` | Execute a natural language query |
| `udb data search QUERY` | Search entities and facts by keyword or semantic similarity |
| `udb data list` | List all entities, property values, and facts |
| `udb data import FILE` | Import instance data from `udb data export` output (KG only) |
| `udb data export` | Export instance data (entities, facts, property values) as JSON |
| `udb data extract TEXT` | Extract entities/facts from free text via LLM |
| `udb data source list` | List sources; KG-only entries marked `(*)` |
| `udb data source add FILE` | Register a file source and optionally extract |
| `udb data source remove NAME` | Remove a source from the registry (KG data preserved) |

`data query` options:

| Option | Description |
|--------|-------------|
| `--session SESSION_ID` | Session ID for query context and interaction |
| `--format table\|json\|nl` | Output format (default: `table`) |
| `--top-k N` | Max results (default: 10) |

**Example**

```
$ udb --database alice data query "jobs suitable for me" --format table

 Query                               Results
 What skills does the user have?     Python, SQL, machine learning
 Does the user prefer remote work?   Yes
```

`data source add` — two types:

```bash
# Type 1 — register source only
udb data source add resume.txt
# Registered source: resume.txt

# Type 2 — register + extract
udb data source add resume.txt \
  --query "What skills does the user have?" \
  --query "What is the user's most recent job title?"
# Added source: resume.txt (2 queries)
```

---

### `udb schema`

All `schema` commands require an active database.

| Command | Description |
|---------|-------------|
| `udb schema list [--format]` | List classes, relations, and their properties |
| `udb schema import FILE` | Import a schema (idempotent) |
| `udb schema export [-o FILE]` | Export schema as JSON |
| `udb schema search QUERY` | Search schema elements by keyword or semantic similarity |

---

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | `UDbError` — message printed via Rich to stderr |
| 2 | Bad arguments (Click default) |
