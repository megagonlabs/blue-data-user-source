# blue-data-user-mcp

MCP server that exposes `UserSource` operations as tools for LLM clients (Claude
Desktop, Claude Code, and any MCP-compatible host).

An LLM agent connected through this server can create and manage user databases,
run natural-language queries against per-user knowledge graphs, read and write
metadata, and manage contact methods.

---

## Installation

```bash
cd platform/mcp

# Install the core library first
pip install -e ../../lib

# Install the MCP server
pip install -e .
```

---

## Running

```bash
# Default: file-backed store at ~/.udb, stdio transport
udb-mcp

# With a specific data directory
BLUE_DATA_USER_SOURCE_DATA_DIR=/path/to/data udb-mcp

# With a custom KB schema
BLUE_DATA_USER_SOURCE_DATA_DIR=/path/to/data BLUE_DATA_USER_SOURCE_SCHEMA_PATH=/path/to/schema.json udb-mcp
```

Note: this server does not read the `udb` CLI's `~/.udb/registry.json` if
`BLUE_DATA_USER_SOURCE_DATA_DIR` is changed from the default — it owns one independently-configured
`FileUserSource` for the process lifetime. Pointing both the CLI and this server
at the same `BLUE_DATA_USER_SOURCE_DATA_DIR` (the default `~/.udb`) gives practical continuity.

---

## Claude Desktop integration

Add to `~/.config/claude-desktop/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "blue-data-user": {
      "command": "udb-mcp",
      "env": {
        "BLUE_DATA_USER_SOURCE_DATA_DIR": "/path/to/data"
      }
    }
  }
}
```

If `udb-mcp` is not on the system PATH, use the full path:

```json
{
  "mcpServers": {
    "blue-data-user": {
      "command": "/path/to/venv/bin/udb-mcp"
    }
  }
}
```

---

## Configuration reference

All configuration is via environment variables — there is no config file.

| Variable | Default | Description |
|---|---|---|
| `BLUE_DATA_USER_SOURCE_DATA_DIR` | `~/.udb` | Directory where database files are stored |
| `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | _(empty)_ | Path to `schema.json` for KB schema seeding |

---

## Tool reference

### Users (write)

#### `create_database`

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | User name, e.g. `"alice"` |

Creates a new user with file-backed storage under `BLUE_DATA_USER_SOURCE_DATA_DIR`. All paths
(registry, KB, metadata, contacts) are derived from the user name automatically.
Returns `{"name": "...", "created": true}`.

#### `delete_database`

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | User name to delete |

Deletes the user and all their backing data files.

#### `reset_database`

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | User name to reset |

Clears KB data for the user and reseeds the schema. Metadata and contacts are
preserved.

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
| `session` | `str \| None` | Optional session id for query context continuity |

Runs a multi-step agent: contextualises and expands the question, queries the
KB in parallel across sub-questions, assesses result quality, and optionally
requests user clarification via their configured contact method.

---

### Data (write)

#### `add_source`

| Parameter | Type | Description |
|---|---|---|
| `user` | `str` | User name |
| `source` | `str` | Free text or file path identifying the source |
| `name` | `str \| None` | Human-readable label (optional) |
| `description` | `str \| None` | Optional description |
| `original` | `str \| None` | Source's own date, e.g. publication date |
| `queries` | `list[str] \| None` | Guiding extraction questions (optional) |

Without `queries`, registers the source for provenance only (Type 1). With
`queries`, an LLM agent extracts attributes and stores them in the KB (Type 2).

#### `remove_source`

`user`, `source_name` — removes a source from the registry; KB data is preserved.

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

Common keys: `identity.name`, `identity.email`, `preferences.verbosity`,
`preferences.language`, `policy.auto_approve`, `skills`, `availability`.

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
| `protocol` | `str` | `"email"`, `"slack"`, `"sms"`, or `"webhook"` |
| `name` | `str` | Human-readable label |
| `details` | `dict` | Protocol-specific details (see below) |
| `preference` | `int` | Ordering priority — lower = higher priority (default 0) |

Details by protocol:

```
slack   → {"channel": "#alice", "token": "xoxb-..."}
webhook → {"url": "https://hooks.example.com/incoming",
           "response_base_url": "http://localhost:8000",
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
| `smtp_password` | no | `""` | SMTP auth password |
| `smtp_use_tls` | no | `True` | Use STARTTLS |
| `reply_domain` | yes¹ | `"localhost"` | Domain for `Reply-To: interaction-{id}@reply_domain` |
| `response_base_url` | yes¹ | — | Base URL of `udb-api` (link in email body + inbound endpoint) |
| `subject` | no | `"A question for you"` | Email subject |
| `timeout` | no | `300` | Seconds to wait for reply |

¹ Not required when `inbound_provider` is `"stdio"`.

**`inbound_provider: "stdio"`** — prints email to stdout and reads reply from stdin. No SMTP or `udb-api` needed. Useful for local development and testing.

**Inbound webhook providers** (`mailgun`, `postmark`, `sendgrid`) — the provider POSTs the parsed reply to `POST /interactions/email/inbound?provider=<name>` on `udb-api`. Configure your provider to route mail for `interaction-*@{reply_domain}` to that endpoint.

For `webhook`, the agent will `POST` to `url` with:

```json
{
  "interaction_id": "<uuid>",
  "message": "Which delivery address should I use?",
  "response_url": "<response_base_url>/interactions/<uuid>/response"
}
```

The external system posts the user's reply to `response_url`, unblocking the
waiting agent. `response_base_url` must point to a running `udb-api` instance.

#### `update_contact`

`user`, `protocol`, `name`, `details` (optional), `preference` (optional).

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
set_metadata("alice", "skills", ["python", "data science"])

# 3. Add a contact method (email via Mailgun inbound)
add_contact("alice", "email", "work", {
    "address": "alice@example.com",
    "from_address": "agent@udb.example.com",
    "smtp_host": "smtp.example.com",
    "reply_domain": "udb.example.com",
    "response_base_url": "http://localhost:8000",
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
blue_data_user_mcp.server   ← FastMCP app, 20 tool handlers (async)
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
