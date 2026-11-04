# blue-data-user-mcp

MCP server that exposes `UserSource` operations as tools for LLM clients (Claude
Desktop, Claude Code, and any MCP-compatible host).

An LLM agent connected through this server can create and manage user databases,
run natural-language queries against per-user knowledge graphs, group queries and
clarification interactions into sessions, read and write metadata, and manage
contact methods.

See [docs/mcp.md](../../docs/mcp.md) for the complete tool reference. This README covers installation, running the server, and Claude Desktop integration.

---

## Installation

The library and its sibling repos (`blue-data`, `blue-data-kb-source`, `blue-data-doc-source`) are not on PyPI; check the siblings out beside this repo. Then:

```bash
cd platform/mcp
bash scripts/install.sh
```

which runs these two steps:

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
BLUE_DATA_USER_SOURCE_DATA_DIR=/path/to/data BLUE_DATA_USER_SOURCE_SCHEMA_PATH=/path/to/schema.json blue-userdb-mcp
```

Note: this server does not read the `blue-userdb` CLI's `~/.blue-userdb/registry.json` if
`BLUE_DATA_USER_SOURCE_DATA_DIR` is changed from the default — it owns one independently-configured
`FileUserSource` for the process lifetime. Pointing both the CLI and this server
at the same `BLUE_DATA_USER_SOURCE_DATA_DIR` (the default `~/.blue-userdb`) gives practical continuity.

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

| Variable | Default | Description |
|---|---|---|
| `BLUE_DATA_USER_SOURCE_DATA_DIR` | `~/.blue-userdb` | Directory where database files are stored |
| `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | _(empty)_ | Path to `schema.json` for KB schema seeding |
| `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` | _(packaged `metadata_schema.json`)_ | Path to a custom metadata schema |
| `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` | _(packaged `contact_schema.json`)_ | Path to a custom contact schema |

---

## Tool reference

### Users (write)

#### `create_database`

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | User name, e.g. `"alice"` |
| `doc_search_mode` | `str` (optional) | How the user's documents are searched: `"vector"` (by meaning; default), `"hybrid"` (meaning and keywords) or `"bm25"` (keywords; its index lasts only for the server process that added the documents) |
| `doc_embedding_model` | `str` (optional) | `"openai"` (default; `text-embedding-3-small`, needs `OPENAI_API_KEY`) or `"dummy"` (a hash, no API calls; only with `"bm25"`) |

Only these named values are accepted, never a class or a connection (#134); `"vector"` or `"hybrid"` with `"dummy"` returns an error. `get_database` reports the choice under `doc_source`.

Creates a new user with file-backed storage under `BLUE_DATA_USER_SOURCE_DATA_DIR`. All paths
(registry, KB, metadata, contacts, sessions) are derived from the user name automatically,
including a file-backed vector store for per-session interaction transcripts.
Returns `{"name": "...", "created": true}`.

#### `delete_database`

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | User name to delete |

Deletes the user and all their backing data files. Only files inside the data directory are deleted: a store path recorded outside it, or reached through a symlink out of it, is kept and logged (#156). Any kept paths are listed under `not_deleted`.

#### `reset_database`

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | User name to reset |

Clears the user's KB data, ingested documents, metadata, contact methods and session history, and
reseeds the schemas. The user stays registered. This cannot be undone. Paths outside the data directory
are kept and listed under `not_deleted`.

---

### Users (read)

#### `list_databases`

No parameters. Returns a list of registered user names.

#### `get_database`

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | User name |

Returns registry properties for the user (storage paths, class, schema paths).

---

### Query

#### `query`

| Parameter | Type | Description |
|---|---|---|
| `user` | `str` | User name (database to query) |
| `question` | `str` | Natural-language question |
| `output_form` | `str` | `"json"` (default — structured rows) or `"nl"` (prose) |
| `session` | `str \| None` | Session id to append this query to (reused). Omit to auto-create a new single-query session — **reuse-or-create** |
| `include_expanded` | `bool` | If `True` (default `False`), also return the per-sub-question queries and their raw results alongside the synthesized answer |
| `max_subqueries` | `int \| None` | Most sub-questions added to the question, each answered by the KB's agent; `0` answers it alone (default: as many as needed, at most 5) |
| `max_kb_turns` | `int \| None` | Most tool-calling turns of the KB's agent per sub-question (default 25) |
| `max_interaction_rounds` | `int \| None` | Most rounds of clarification questions (default 3) |

A query makes dozens of LLM calls at the defaults; the `max_*` parameters bound them (see [Cost](../../docs/guide.md#cost)).

Runs a multi-step agent: contextualises and expands the question, queries the
KB in parallel across sub-questions, assesses result quality, and optionally
requests user clarification via their configured contact method. Returns
`{"results": [...], "session_id": "..."}` — `session_id` is the reused or
newly-created session; pass it back as `session` on the next call to continue
the same conversation.

---

### Sessions

#### `session_start`

`user` — creates a new session for the user. Returns `{"user": "...", "session_id": "..."}`.

#### `session_end`

`user`, `session_id` — ends a session; further queries against it are rejected.
Returns `{"user": "...", "session_id": "...", "ended": true}`.

#### `get_session`

`user`, `session_id` — returns the session's record: `{"session_id": "...", "created_at": ..., "ended_at": ..., "status": ..., "doc_source_name": ..., "queries": {...}}`. See [10-data-model.md](../../design/10-data-model.md) §6 for the full query/interaction schema.

#### `list_sessions`

`user` — returns `dict[session_id, record]` for all sessions.

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

Without `queries`, registers the file and indexes it for search (Type 1). With
`queries`, an LLM agent extracts attributes and stores them in the KB (Type 2).

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

Common keys: `identity.name`, `identity.pronouns`, `identity.timezone`,
`preferences.verbosity`, `preferences.language`, `availability.preferred_channel`,
`availability.out_of_office`, `privacy.consent_level`. See
[data/metadata_schema.json](../../lib/src/blue_data_user_source/data/metadata_schema.json)
for the full seeded schema (identity, preferences, availability, privacy) — arbitrary
keys can still be set, but only these are seeded with defaults and read by the
reasoning/interaction logic.

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
| `protocol` | `str` | `"stdio"`, `"email"`, or `"webhook"` (interaction handlers exist for these three). `"sms"`, `"session"`, `"messaging"`, `"enterprise"`, and `"notification"` can also be recorded, but are never used to contact the user — contact selection skips them |
| `name` | `str` | Human-readable label |
| `details` | `dict` | Protocol-specific details (see below) |
| `preference` | `int` | Ordering priority — lower = higher priority (default 0) |

Details by protocol:

```
stdio   → {} (no details needed — prints to stdout, reads from stdin)
webhook → {"url": "https://hooks.example.com/incoming",
           "response_base_url": "http://localhost:8003",
           "timeout": 300}
```

**Email** has its own set of detail keys:

| Key | Required | Default | Description |
|---|---|---|---|
| `address` | yes | — | Recipient email address |
| `inbound_provider` | no | _(none)_ | How the reply arrives: `mailgun`, `postmark`, `sendgrid`, `smtp_server`, or `stdio` |
| `from_address` | yes¹ | `"agent"` | Displayed in From: |
| `smtp_host` | yes¹ | — | SMTP server hostname |
| `smtp_port` | no | `587` | SMTP port |
| `smtp_user` | no | `from_address` | SMTP auth username |
| `smtp_password` | no | `""` | SMTP auth password. Masked on reads; may be a `$VAR` reference |
| `smtp_use_tls` | no | `True` | Use STARTTLS |
| `reply_domain` | yes¹ | `"localhost"` | Domain for `Reply-To: interaction-{id}@reply_domain` |
| `response_base_url` | yes¹ | — | Base URL of `blue-userdb-api` (link in email body + inbound endpoint) |
| `subject` | no | `"A question for you"` | Email subject |
| `timeout` | no | `300` | Seconds to wait for reply |

¹ Not required when `inbound_provider` is `"stdio"`.

**Secrets.** `smtp_password`, a webhook's `url` and `headers`, and a notification `endpoint` are secret: every read path (REST, MCP tools, `blue-userdb contact list/get`) returns them masked as `***`. To keep `smtp_password`, a webhook's `url` or a header value out of the contacts store too, store a reference to an environment variable instead, e.g. `"smtp_password": "$BLUE_DATA_USER_CONTACT_SMTP_PASSWORD"`; it is resolved when a message is sent, and shown as-is on reads. Only variables named `BLUE_DATA_USER_CONTACT_*` can be referenced: any other name is refused when the contact is written, and fails the clarification when it is used, so a contact cannot read the server's other settings.

**`inbound_provider: "stdio"`** — prints email to stdout and reads reply from stdin. No SMTP or `blue-userdb-api` needed. Useful for local development and testing.

**Inbound webhook providers** (`mailgun`, `postmark`, `sendgrid`) — the provider POSTs the parsed reply to `POST /interactions/email/inbound?provider=<name>` on `blue-userdb-api`. Configure your provider to route mail for `interaction-*@{reply_domain}` to that endpoint.

For `webhook`, the agent will `POST` to `url` with:

```json
{
  "interaction_id": "<uuid>",
  "message": "Which delivery address should I use?",
  "response_url": "<response_base_url>/interactions/<uuid>/response"
}
```

The external system posts the user's reply to `response_url`, unblocking the
waiting agent. `response_base_url` must point to a running `blue-userdb-api` instance using the same data directory as this server: that shared store is how the reply reaches the waiting query, which picks it up within a second.

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
set_metadata("alice", "preferences.verbosity", "brief")
set_metadata("alice", "availability.preferred_channel", "email")

# 3. Add a contact method (email via Mailgun inbound)
add_contact("alice", "email", "work", {
    "address": "alice@example.com",
    "from_address": "agent@blue-userdb.example.com",
    "smtp_host": "smtp.example.com",
    "reply_domain": "blue-userdb.example.com",
    "response_base_url": "http://localhost:8003",
    "inbound_provider": "mailgun",
}, preference=1)

# Or for local development (stdio mode — no SMTP needed)
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
blue_data_user_mcp.server   ← FastMCP app, 23 tool handlers (async)
        │
blue_data_user_mcp.config   ← singleton FileUserSource factory (BLUE_DATA_USER_SOURCE_* env vars)
        │
   UserSource                ← lib/src/blue_data_user_source/
   └── FileUserSource        ← file-backed registry + per-user KB/metadata/contacts
```

The server holds a single `FileUserSource` instance per process. All tool calls
share that instance; `user` is a plain string argument selecting the logical
database (user) within it.

---

## Running tests

```bash
cd platform/mcp
pytest
```

Tests inject an in-memory `MemoryUserSource` directly — no file I/O, no network,
no API key required. The query test mocks `async_execute_query`.
