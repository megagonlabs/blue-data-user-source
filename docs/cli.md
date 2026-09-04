# udb CLI

Command-line interface for the user database — a per-user knowledge store with natural language querying. A thin adapter over the `blue-data-user-source` Python library built with Click and Rich.

## Requirements

- Python 3.10+
- [`blue-data-user-source`](../lib) (local dependency)

## Installation

```bash
cd platform/cli
pip install -e .
```

`click`, `rich`, and `arrow` are pulled in automatically. Set your OpenAI API key for extraction or query commands:

```bash
export OPENAI_API_KEY=sk-...
```

## State persistence

Data is persisted under `~/.udb/` by default:

```
~/.udb/
├── .selected.database          # active database name (written by 'database select'/'create')
├── .selected.session            # active session id (written by 'session select'/'start', and auto-created sessions)
├── registry.json               # outer registry (users + source properties)
├── registries/
│   └── alice.json              # per-user registry (sources registered for alice)
└── sources/
    └── alice/
        ├── alice.json          # per-user knowledge graph (file KB backend)
        ├── metadata.json       # user metadata
        ├── contacts.json       # user contact methods
        ├── sessions.json       # session / query / interaction records
        └── sessions/           # per-session interaction transcripts (file vector backend)
```

Override the data directory globally:

```bash
export BLUE_DATA_USER_SOURCE_DATA_DIR=/path/to/my-udb
```

## Global options

```
udb [--database NAME] [--data-dir DIR] [--schema-path PATH] COMMAND
```

| Option | Env var | Default | Description |
|---|---|---|---|
| `--database NAME` | `BLUE_DATA_USER_SOURCE_DATABASE` | — | Active database (user) name |
| `--data-dir DIR` | `BLUE_DATA_USER_SOURCE_DATA_DIR` | `~/.udb` | Directory where database files are stored |
| `--schema-path PATH` | `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | — | Path to a custom `schema.json` for KB schema seeding |

`--database` can also be set persistently with `udb database select NAME`, which writes to `~/.udb/.selected.database`.

## Walkthrough

```bash
# 1. Create a database (auto-selects it)
$ udb database create alice
Created database: alice

# 2. Set some metadata
$ udb metadata set identity name "Alice Smith"
Set identity.name = Alice Smith
$ udb metadata list identity
┏━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Key      ┃ Value       ┃ Description                  ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ name     │ Alice Smith │ Full name.                    │
│ pronouns │ —           │ Preferred pronouns (…).        │
│ locale   │ —           │ IETF locale tag (…).           │
│ timezone │ —           │ IANA timezone (…).             │
└──────────┴─────────────┴──────────────────────────────┘

# 3. Register a contact method (stdio dev mode for local testing)
$ udb contact add email dev --preference 0
Added contact: email/dev
$ udb contact set email dev inbound_provider stdio
Set email.dev.inbound_provider = stdio

# 4. Register a data source
$ udb data source add resume.txt \
    --query "What skills does the user have?" \
    --query "What is the user's most recent job title?"
Added source: resume.txt (2 queries extracted to KB)

# 5. Query
$ udb data query "What jobs are suitable for me?"
 Query                               Results
 What skills does the user have?     Python, SQL, machine learning
 Does the user prefer remote work?   Yes

# 6. Sessions
$ udb session start
Created session: 1c1919ff-9881-4429-8c52-ab6abae6ff1a (selected)
$ udb data query "What about remote roles?"
$ udb session show
$ udb session end

# 7. Inspect and clean up
$ udb data list
$ udb database delete alice --yes
Deleted database: alice
```

---

## `udb database`

Manage user databases.

| Command | Description |
|---|---|
| `udb database list [--format table\|json]` | List all registered databases |
| `udb database create NAME [options]` | Create a new database, and select it as active |
| `udb database delete NAME [--yes]` | Delete a database and all its data |
| `udb database select NAME` | Set the active database |
| `udb database search KEYWORD [--format]` | Keyword search over database names |
| `udb database reset [--yes]` | Clear KB data for the active database and reseed the schema |
| `udb database config show [--format]` | Show stored configuration for the active database |

`database create` options:

| Option | Default | Description |
|---|---|---|
| `--kb-backend` | `file` | KB backend: `memory`, `file`, or `neo4j` |
| `--neo4j-host` | `localhost` | Neo4j host (`neo4j` backend only) |
| `--neo4j-port` | `7687` | Neo4j bolt port |
| `--neo4j-user` | `neo4j` | Neo4j username |
| `--neo4j-password` | — | Neo4j password (required for `neo4j` backend) |
| `--doc-backend` | `file` | Vector backend for per-session/per-file document stores: `memory` or `file` |

```bash
udb database create alice --kb-backend neo4j \
    --neo4j-host db.example.com --neo4j-password secret
```

---

## `udb session`

A session groups the queries and clarification interactions of one conversation. `udb data query` uses whatever session is selected (or auto-creates one if none is), the same way `udb database select` works for databases.

| Command | Description |
|---|---|
| `udb session start` | Create a new session for the active database and select it |
| `udb session select SESSION_ID` | Set the active session |
| `udb session end [SESSION_ID]` | End a session (defaults to the selected one); clears the selection if it matches |
| `udb session list [--format]` | List sessions for the active database |
| `udb session show [SESSION_ID] [--format]` | Show a session's queries and interactions (defaults to the selected one) |

**Resolution order** for the session used by `udb data query`: `--session` flag → `BLUE_DATA_USER_SOURCE_SESSION` env var → `.selected.session` file. Unlike database selection, an unresolved session is **not** an error — the query auto-creates a new session and writes it to `.selected.session`, so the next query continues it automatically.

---

## `udb data`

Instance data management. All `data` commands require an active database.

| Command | Description |
|---|---|
| `udb data list [--show-provenance] [--show-detailed] [--format table\|json]` | List entities, property values, and facts |
| `udb data query TEXT [options]` | Execute a natural-language query |
| `udb data search QUERY [options]` | Search entities and facts by keyword or semantic similarity |
| `udb data import FILE` | Import instance data from `udb data export` output (KG only) |
| `udb data export [--show-provenance] [-o FILE]` | Export instance data as JSON |
| `udb data extract TEXT [options]` | Extract entities/facts from free text via LLM |

`data query` options:

| Option | Description |
|---|---|
| `--session SESSION_ID` | Session to append this query to — falls back per the resolution order above |
| `--format table\|json\|nl` | Output format (default `table`) |
| `--top-k N` | Max results (default 10) |
| `--verbose` / `-v` | Show tool-call arguments in the status line |
| `--log` / `-l` | Also print each tool call and result on its own persistent line |
| `--log-limit N` | Truncation length for verbose/log output (default 80) |

`data search` options: `--type entity|fact` (repeatable), `--mode keyword|semantic`, `--top-k N`, `--format table|json`.

`data extract` options: `--query QUESTION` (repeatable), `--source NAME`, `--model MODEL` (default `gpt-4o`), plus `--verbose`/`-v`, `--log`/`-l`, `--log-limit`.

```bash
udb --database alice data query "What jobs are suitable for me?" --format nl
udb data extract "Alice joined Acme Corp in 2019 as a data scientist." \
    --query "What role does Alice have?"
```

### `udb data source`

| Command | Description |
|---|---|
| `udb data source list [--show-detailed] [--format]` | List registry sources and KG `SOURCE` nodes; KG-only entries marked `(*)` |
| `udb data source add FILE [options]` | Register a file as a source — always ingested into `external_documents`; optionally extracted into the KG |
| `udb data source remove NAME [--yes]` | Remove a source from the registry (KG data preserved) |

`source add` options: `--query QUESTION` (repeatable — presence triggers Type 2), `--name`, `--description`, `--original`.

```bash
udb data source add resume.txt                                  # Type 1
udb data source add resume.txt --query "What skills?"            # Type 2
```

---

## `udb schema`

Schema management. All `schema` commands require an active database.

| Command | Description |
|---|---|
| `udb schema list [--format]` | List classes, relations, and their properties |
| `udb schema import FILE` | Import a schema (idempotent) |
| `udb schema export [-o FILE]` | Export the schema as JSON |
| `udb schema search QUERY [--type]` | Search schema elements by keyword or semantic similarity |

---

## `udb metadata`

User metadata for agents acting on your behalf — dot-path addressed, backed by [`data/metadata_schema.json`](../lib/src/blue_data_user_source/data/metadata_schema.json).

| Command | Description |
|---|---|
| `udb metadata list [PATH...] [-r\|--recursive] [--format table\|json]` | List categories, or the fields under a path; `--recursive` flattens everything below the path into `key = value` rows |
| `udb metadata get PATH...` | Get a single value (dotted path given as space-separated segments) |
| `udb metadata set PATH... VALUE` | Set a value — all but the last argument are path segments |
| `udb metadata delete PATH... [--yes]` | Delete a key |

Values passed to `set` are parsed as JSON when possible (numbers, booleans, `null`, arrays, objects), otherwise kept as a plain string.

```bash
udb metadata list                                        # top-level categories with counts
udb metadata list identity                                 # fields under "identity"
udb metadata list --recursive                              # every set + unset schema field, flattened
udb metadata set identity name "Alice"
udb metadata set preferences verbosity brief
udb metadata set availability preferred_channel email
udb metadata get privacy consent_level
udb metadata delete identity pronouns
```

Categories: `identity` (name, pronouns, locale, timezone), `preferences` (communication_style, verbosity, language), `availability` (working_hours, preferred_channel, out_of_office, by_topic), `privacy` (data_sharing_preference, sensitive_categories, retention_days, consent_level).

---

## `udb contact`

Contact methods for agents to reach you — dot-path addressed by protocol/name/field, backed by [`data/contact_schema.json`](../lib/src/blue_data_user_source/data/contact_schema.json).

| Command | Description |
|---|---|
| `udb contact list [PATH...] [-r\|--recursive] [--format table\|json]` | List protocols, or named entries under a protocol, or fields of one entry |
| `udb contact get PROTOCOL NAME [FIELD...]` | Get an entry or a specific field |
| `udb contact set PROTOCOL NAME FIELD... VALUE` | Set a field on an entry |
| `udb contact add PROTOCOL NAME [--preference N]` | Create a named entry (set its remaining fields with `contact set` afterwards) |
| `udb contact remove PROTOCOL NAME [--yes]` | Remove a named entry |

```bash
udb contact list                                    # protocols with entry counts
udb contact add email work
udb contact set email work address alice@example.com
udb contact set email work inbound_provider stdio
udb contact list email --recursive
udb contact get email work address
udb contact remove email work
```

Protocols: `email`, `webhook`, `sms`, `messaging`, `enterprise`, `notification`, `session`, `stdio` — see [api-reference.md](api-reference.md#contactmanager--contactmethod) for detail keys per protocol. Only `stdio`, `email`, and `webhook` have a working `interact()` implementation today; the rest can be recorded via this command but aren't yet reachable by the interaction layer.

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | `UDbError` — message printed via Rich to stderr |
| 2 | Bad arguments (Click default) |

---

## Project structure

```
platform/cli/
├── pyproject.toml
├── src/
│   └── blue_data_user_cli/
│       ├── __init__.py
│       └── commands.py   # Click command groups: database, session, data (+ source), schema, metadata, contact
└── tests/
    └── unit/
```

## Running tests

```bash
cd platform/cli
pytest
```

The CLI test suite covers command parsing and output formatting with an all-memory backend — no API key or network access required.
