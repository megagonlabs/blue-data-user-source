# blue-data-user-mcp

MCP server that exposes `UserSource` operations as tools for LLM clients (Claude Desktop, Claude Code, and any MCP-compatible host).

An LLM agent connected through this server can create and manage user databases, run natural-language queries against per-user knowledge graphs, group queries and clarification interactions into sessions, read and write metadata, and manage contact methods.

---

## Installation

```bash
cd platform/mcp
bash scripts/install.sh
```

The script installs the library first with `lib/scripts/install.sh`, which installs the sibling repos (`blue-data`, `blue-data-kb-source`, `blue-data-doc-source`) from checkouts beside this repo: none of them is on PyPI. Or step by step, from `platform/mcp`:

```bash
bash ../../lib/scripts/install.sh   # the sibling repos, then the library
pip install -e '.[dev]'             # the server, with pytest for its tests
```

---

## Running

```bash
# Default: file-backed store at ~/.blue-userdb, stdio transport
blue-userdb-mcp

# With a specific data directory
BLUE_DATA_USER_SOURCE_DATA_DIR=/path/to/data blue-userdb-mcp

# With a custom KB schema
BLUE_DATA_USER_SOURCE_DATA_DIR=/path/to/data \
BLUE_DATA_USER_SOURCE_SCHEMA_PATH=/path/to/schema.json \
    blue-userdb-mcp
```

The LLM provider's key is required for the `query` tool's rewriting/expansion/assessment prompts and for `add_source` calls that pass `queries`: `OPENAI_API_KEY` by default, or `ANTHROPIC_API_KEY` with `BLUE_DATA_LLM_PROVIDER=anthropic`. The models resolve from the environment as in the library (see [installation](installation.md#environment-variables)).

Note: this server does **not** read the `blue-userdb` CLI's `~/.blue-userdb/registry.json` if `BLUE_DATA_USER_SOURCE_DATA_DIR` is changed from the default — it owns one independently-configured `FileUserSource` for the process lifetime. Pointing both the CLI and this server at the same `BLUE_DATA_USER_SOURCE_DATA_DIR` (the default `~/.blue-userdb`) gives practical continuity.

---

## Claude Desktop integration

Add to `~/.config/claude-desktop/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "blue-data-user": {
      "command": "blue-userdb-mcp",
      "env": {
        "BLUE_DATA_USER_SOURCE_DATA_DIR": "/path/to/data"
      }
    }
  }
}
```

If `blue-userdb-mcp` is not on the system PATH, use the full path:

```json
{
  "mcpServers": {
    "blue-data-user": {
      "command": "/path/to/venv/bin/blue-userdb-mcp"
    }
  }
}
```

---

## Conventions

- **Transport: stdio.** The server is a local process that acts for the user on their machine, like the rest of the Blue Data family's MCP servers; it opens no network port. (An HTTP surface is `blue-userdb-api`.)
- **Tools only, no resources.** Every operation, reads included, is a tool, since most reads take parameters (`user`, a key, a filter).
- **Results and errors.** Every tool returns JSON text. On success it is the tool's payload, as documented per tool below. On failure it is `{"error": "<message>"}`, returned as normal content, not as an MCP `isError` result, so an agent can read the reason and recover. Every tool follows this rule.
- **No `--format`.** The CLI's `--format table|json|nl` does not carry over: MCP results are always JSON. (`query` still takes `output_form`, which picks a table of rows or a prose answer *inside* the JSON.)
- **Parameter schemas.** Every parameter has a description, and fixed-value parameters (`output_form`, `protocol`) are JSON Schema enums. The server refuses to start if a tool's parameter is undocumented.
- **Secrets.** Read tools (`list_contacts`, `get_contact`) mask contact secrets as `***`. Pass secrets to `add_contact` / `update_contact` as references to `BLUE_DATA_USER_CONTACT_*` environment variables (e.g. `"smtp_password": "$BLUE_DATA_USER_CONTACT_SMTP_PASSWORD"`) so they never appear in a tool call; any other variable is refused; sending a masked value back keeps the stored secret.
- **Scope.** Not exposed, deliberately: schema management (`blue-userdb schema ...`), keyword/semantic `data search`, `data export` / `import` / `extract`, onboarding (an interactive interview, which a server cannot hold — #120), and the CLI's own state (`database select`, `session select`, profiles). Use the CLI or the library for those; an agent works with users, sources, queries, sessions, metadata and contacts.
- **Configuration** comes only from `BLUE_DATA_USER_SOURCE_*` environment variables (below). The server deliberately does not read the CLI's profiles, so a developer's CLI profile cannot reconfigure a running server.

## Configuration reference

All configuration is via environment variables — there is no config file.
These share their names with the `blue-userdb` CLI's profile parameters but nothing else: the server reads the environment only, never `~/.blue-userdb/.profiles` or the selected profile. A CLI profile cannot reconfigure a running server.

| Variable | Default | Description |
|---|---|---|
| `BLUE_DATA_USER_SOURCE_DATA_DIR` | `~/.blue-userdb` | Directory where database files are stored |
| `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | _(empty)_ | Path to a custom `schema.json` for KB schema seeding |
| `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` | _(packaged `metadata_schema.json`)_ | Path to a custom metadata schema |
| `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` | _(packaged `contact_schema.json`)_ | Path to a custom contact schema |

---

## Tool reference

Tool groups: Users (write/read), Query, Sessions, Data (write/read), Metadata (write/read), Contacts (write/read) — 23 tools total.

### Users (write)

#### `create_database`

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | User name, e.g. `"alice"` |
| `doc_search_mode` | `str` (optional) | How the user's documents are searched: `"vector"` (by meaning; default), `"hybrid"` (meaning and keywords) or `"bm25"` (keywords; its index lasts only for the server process that added the documents) |
| `doc_embedding_model` | `str` (optional) | `"openai"` (default; `text-embedding-3-small`, needs `OPENAI_API_KEY`) or `"dummy"` (a hash, no API calls; only with `"bm25"`) |

Only these named values are accepted, never a class or a connection (#134); `"vector"` or `"hybrid"` with `"dummy"` returns an error. `get_database` reports the choice under `doc_source`.

Creates a new user with file-backed storage under `BLUE_DATA_USER_SOURCE_DATA_DIR`. All paths (registry, KB, metadata, contacts, sessions) are derived from the user name automatically, including a file-backed vector store for per-session/per-file document ingestion. Returns `{"name": "...", "created": true}`.

#### `delete_database`

`name` — deletes the user and all their backing data files. Only files inside the data directory are deleted: a store path recorded outside it, or reached through a symlink out of it, is kept and logged (#156). Any kept paths are listed under `not_deleted`.

#### `reset_database`

`name` — clears the user's KB data, ingested documents, metadata, contact methods and session history, and reseeds the schemas. The user stays registered. This cannot be undone. Paths outside the data directory are kept and listed under `not_deleted`.

---

### Users (read)

#### `list_databases`

No parameters. Returns a list of registered user names.

#### `get_database`

`name` — returns registry properties for the user (storage paths, class, schema paths).

---

### Query

#### `query`

| Parameter | Type | Description |
|---|---|---|
| `user` | `str` | User name (database to query) |
| `question` | `str` | Natural-language question |
| `output_form` | `str` | `"json"` (default — structured rows) or `"nl"` (prose) |
| `session` | `str \| None` | Session id to append this query to (reused). Omit to auto-create a new single-query session |
| `include_expanded` | `bool` | If `True`, also return the per-sub-question queries and their raw results alongside the synthesized answer (default `False`) |
| `max_subqueries` | `int \| None` | Most sub-questions added to the question, each answered by the KB's agent; `0` answers it alone (default: as many as needed, at most 5) |
| `max_kb_turns` | `int \| None` | Most tool-calling turns of the KB's agent per sub-question (default 25) |
| `max_interaction_rounds` | `int \| None` | Most rounds of clarification questions (default 3) |

A query makes dozens of LLM calls at the defaults; the `max_*` parameters bound them (see [Cost](guide.md#cost)).

Runs a multi-step agent: contextualizes and expands the question (resolving self-references to the user's actual name), retrieves data for each sub-question from the KB and any registered documents, assesses result quality, and optionally requests user clarification via their configured contact method. Returns `{"results": [...], "session_id": "..."}` — pass `session_id` back as `session` on the next call to continue the same conversation.

---

### Sessions

| Tool | Params | Returns |
|---|---|---|
| `session_start` | `user` | `{"user": "...", "session_id": "..."}` |
| `session_end` | `user`, `session_id` | `{"user": "...", "session_id": "...", "ended": true}` |
| `get_session` | `user`, `session_id` | `{"session_id": "...", "created_at": ..., "ended_at": ..., "status": ..., "doc_source_name": ..., "queries": {...}}` |
| `list_sessions` | `user` | `dict[session_id, record]` |

See [10-data-model.md](../design/10-data-model.md) §6 for the full query/interaction record schema.

---

### Data (write)

#### `add_source`

| Parameter | Type | Description |
|---|---|---|
| `user` | `str` | User name |
| `source` | `str` | Path to the file to ingest, on the machine running the MCP server |
| `name` | `str \| None` | Human-readable label (optional) |
| `description` | `str \| None` | Optional description |
| `original` | `str \| None` | Source's own date, e.g. publication date |
| `queries` | `list[str] \| None` | Guiding extraction questions (optional) |

Without `queries`, registers the file and indexes it for search (Type 1). With `queries`, an LLM agent extracts attributes and stores them in the KB (Type 2).

#### `remove_source`

`user`, `source_name` (name or id) — removes the source: its document leaves search and query answers; facts extracted from it are kept. Errors when no source, or more than one, has that name.

---

### Data (read)

#### `list_data`

`user` — returns all ingested data entries in the user's knowledge graph.

#### `list_sources`

`user`, `source_id` (optional) — returns registered sources for the user.

---

### Metadata (write)

#### `set_metadata`

| Parameter | Type | Description |
|---|---|---|
| `user` | `str` | User name |
| `key` | `str` | Dot-separated key, e.g. `"preferences.verbosity"` |
| `value` | `Any` | Value to store (string, number, boolean, list, or dict) |

Common keys: `identity.name`, `identity.timezone`, `preferences.verbosity`, `preferences.language`, `availability.preferred_channel`, `privacy.consent_level`.

#### `delete_metadata`

`user`, `key` — deletes the metadata key.

---

### Metadata (read)

#### `get_metadata`

`user`, `key` — returns a single metadata value.

#### `list_metadata`

`user` — returns all metadata as a dict.

---

### Contacts (write)

#### `add_contact`

| Parameter | Type | Description |
|---|---|---|
| `user` | `str` | User name |
| `protocol` | `str` | `"stdio"`, `"email"` or `"webhook"` — the protocols with a transport. `"sms"`, `"messaging"`, `"enterprise"`, `"notification"` and `"session"` can be recorded but are never used to contact the user — contact selection skips them |
| `name` | `str` | Human-readable label |
| `details` | `dict` | Protocol-specific details (see [cli.md](cli.md#blue-userdb-contact) / [api-reference.md](api-reference.md#contactmanager--contactmethod)) |
| `preference` | `int` | Ordering priority — lower = higher priority (default 0) |

```
email   → {"address": "alice@example.com", "inbound_provider": "stdio"}   # dev mode, no SMTP needed
webhook → {"url": "https://hooks.example.com/incoming",
           "response_base_url": "http://localhost:8003", "timeout": 300}
```

`response_base_url` is the address of a running `blue-userdb-api` that uses the same data directory as this server: the reply goes there, and reaches the waiting query through that shared store. The tool call blocks until the reply or the contact's `timeout`.

For a production email contact, also set `from_address`, `smtp_host`, `reply_domain`, `response_base_url`, and an `inbound_provider` of `mailgun`, `postmark`, or `sendgrid` — see [api.md](api.md#email-contact-method) for the full key set and the inbound webhook wiring.

#### `update_contact`

`user`, `protocol`, `name`, `details` (optional), `preference` (optional). `details` replaces the stored fields (the preference is kept unless given); a secret field sent back masked as `***` keeps its stored value.

#### `remove_contact`

`user`, `protocol`, `name`.

---

### Contacts (read)

#### `list_contacts`

`user`, `protocol` (optional filter) — returns all contact methods.

#### `get_contact`

`user`, `protocol`, `name` — returns a single contact method.

---

## Typical session

```
# 1. Create a user
create_database("alice")

# 2. Add metadata
set_metadata("alice", "identity.name", "Alice Smith")
set_metadata("alice", "identity.timezone", "America/New_York")
set_metadata("alice", "preferences.verbosity", "brief")

# 3. Add a contact method (stdio dev mode — no SMTP needed)
add_contact("alice", "email", "dev", {
    "address": "alice@example.com",
    "inbound_provider": "stdio",
}, preference=0)

# 4. Ingest a source with extraction queries
add_source("alice", "alice_resume.txt",
           name="resume",
           queries=["What skills does Alice have?",
                    "What companies has Alice worked at?"])

# 5. Query
query("alice", "What jobs are suitable for Alice?")
query("alice", "Summarize Alice's work history", output_form="nl")

# 6. Inspect data
list_data("alice")
list_sources("alice")
```

---

## Architecture

```
Claude / MCP client
        │  MCP (stdio transport)
        ▼
blue_data_user_mcp.server   ← FastMCP app, 20 tool handlers (async)
        │
blue_data_user_mcp.config   ← singleton FileUserSource factory (BLUE_DATA_USER_SOURCE_* env vars)
        │
   UserSource                ← lib/src/blue_data_user_source/
   └── FileUserSource         ← file-backed registry + per-user KB/metadata/contacts/sessions
```

The server holds a single `FileUserSource` instance per process. All tool calls share that instance; `user` is a plain string argument selecting the logical database (user) within it. Unlike the `blue-userdb` CLI, this server does not layer `--database`/`--data-dir` flags — every path is derived from `BLUE_DATA_USER_SOURCE_DATA_DIR` and the user name (see `create_database` above).

---

## Running tests

```bash
cd platform/mcp
pytest
```

Tests inject an in-memory `MemoryUserSource` directly — no file I/O, no network, no API key required. The query test mocks `async_execute_query`.
