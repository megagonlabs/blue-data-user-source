# blue-userdb CLI

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

Data is persisted under `~/.blue-userdb/` by default:

```
~/.blue-userdb/
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
export BLUE_DATA_USER_SOURCE_DATA_DIR=/path/to/my-blue-userdb   # or: blue-userdb profile config BLUE_DATA_USER_SOURCE_DATA_DIR /path/to/my-blue-userdb
```

## Global options

```
blue-userdb [--database NAME] [--session ID] [--data-dir DIR] [--schema-path PATH]
    [--metadata-schema-path PATH] [--contact-schema-path PATH] COMMAND
```

| Option | Env var | Default | Description |
|---|---|---|---|
| `--profile NAME` | — (`BLUE_DATA_PROFILE`) | the selection in `~/.blue-userdb/.selected.profile` | Configuration profile |
| `--database NAME` | `BLUE_DATA_USER_SOURCE_DATABASE` | the selection in `~/.blue-userdb/.selected.database`, then the profile | Active database (user) name |
| `--session ID` | `BLUE_DATA_USER_SOURCE_SESSION` | the selection in `~/.blue-userdb/.selected.session` | Session id for query context |
| `--data-dir DIR` | `BLUE_DATA_USER_SOURCE_DATA_DIR` | `~/.blue-userdb` | Directory where database files are stored |
| `--schema-path PATH` | `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | — | Path to a custom `schema.json` for KB schema seeding |
| `--metadata-schema-path PATH` | `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` | packaged `metadata_schema.json` | Path to a custom metadata schema |
| `--contact-schema-path PATH` | `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` | packaged `contact_schema.json` | Path to a custom contact schema |

Every option falls back to the selected profile (`blue-userdb profile config`); an exported environment variable of the same name still overrides it. Precedence: **command option > environment variable > profile > default**. The database is the one exception: the selection written by `database select` / `database create` sits between the environment variable and the profile — **`--database` > environment variable > `.selected.database` > profile** — so selecting a database works even when the profile names one. The full parameter table is in [platform/cli/README.md](../platform/cli/README.md#profiles-and-configuration).

`--database` can also be set persistently with `blue-userdb database select NAME`, which writes to `~/.blue-userdb/.selected.database`.

## Walkthrough

```bash
# 1. Create a database (auto-selects it)
$ blue-userdb database create alice
Created database: alice

# 2. Set some metadata
$ blue-userdb metadata set identity name "Alice Smith"
Set identity.name = Alice Smith
$ blue-userdb metadata list identity
┏━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Key      ┃ Value       ┃ Description                  ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ name     │ Alice Smith │ Full name.                    │
│ pronouns │ —           │ Preferred pronouns (…).        │
│ locale   │ —           │ IETF locale tag (…).           │
│ timezone │ —           │ IANA timezone (…).             │
└──────────┴─────────────┴──────────────────────────────┘

# 3. Register a contact method (stdio dev mode for local testing)
$ blue-userdb contact add email dev --preference 0
Added contact: email/dev
$ blue-userdb contact set email dev inbound_provider stdio
Set email.dev.inbound_provider = stdio

# 4. Register a data source
$ blue-userdb data source add resume.txt \
    --query "What skills does the user have?" \
    --query "What is the user's most recent job title?"
Added source: resume.txt (2 queries extracted to KB)

# 5. Query
$ blue-userdb data query "What jobs are suitable for me?"
 Query                               Results
 What skills does the user have?     Python, SQL, machine learning
 Does the user prefer remote work?   Yes

# 6. Sessions
$ blue-userdb session start
Created session: 1c1919ff-9881-4429-8c52-ab6abae6ff1a (selected)
$ blue-userdb data query "What about remote roles?"
$ blue-userdb session show
$ blue-userdb session end

# 7. Inspect and clean up
$ blue-userdb data list
$ blue-userdb database delete alice --yes
Deleted database: alice
```

---

## `blue-userdb database`

Manage user databases.

| Command | Description |
|---|---|
| `blue-userdb database list [--format table\|json]` | List all registered databases |
| `blue-userdb database create NAME [options]` | Create a new database, and select it as active |
| `blue-userdb database delete NAME [--yes]` | Delete a database and all its data |
| `blue-userdb database select NAME` | Set the active database |
| `blue-userdb database search KEYWORD [--format]` | Keyword search over database names |
| `blue-userdb database onboard [--no-metadata-onboard]` | Ask the user onboarding questions to seed KB data and metadata |
| `blue-userdb database reset [--yes]` | Clear the active database's KB data, ingested documents, metadata, contacts and sessions, and reseed the schemas |
| `blue-userdb database config show [--format]` | Show the database configuration |
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
blue-userdb database create alice --kb-backend neo4j \
    --neo4j-host db.example.com --neo4j-password secret
```

---

## `blue-userdb session`

A session groups the queries and clarification interactions of one conversation. `blue-userdb data query` uses whatever session is selected (or auto-creates one if none is), the same way `blue-userdb database select` works for databases.

| Command | Description |
|---|---|
| `blue-userdb session start` | Create a session and select it |
| `blue-userdb session select SESSION_ID` | Set the active session |
| `blue-userdb session end [SESSION_ID]` | End a session (defaults to the selected one); clears the selection if it matches |
| `blue-userdb session list [--format]` | List sessions |
| `blue-userdb session show [SESSION_ID] [--format]` | Show a session's queries and interactions (defaults to the selected one) |

**Resolution order** for the session used by `blue-userdb data query`: `--session` flag → `BLUE_DATA_USER_SOURCE_SESSION` env var → `.selected.session` file. Unlike database selection, an unresolved session is **not** an error — the query auto-creates a new session and writes it to `.selected.session`, so the next query continues it automatically.

---

## `blue-userdb data`

Instance data management. All `data` commands require an active database.

| Command | Description |
|---|---|
| `blue-userdb data list [--show-provenance] [--show-detailed] [--format table\|json]` | List entities, property values, and facts |
| `blue-userdb data query TEXT [options]` | Execute a natural-language query |
| `blue-userdb data search QUERY [options]` | Search entities and facts |
| `blue-userdb data import FILE` | Import instance data from `blue-userdb data export` output (KG only) |
| `blue-userdb data export [--show-provenance] [-o FILE]` | Export instance data as JSON |
| `blue-userdb data extract TEXT [options]` | Extract entities/facts from free text via LLM |

`data query` options:

| Option | Description |
|---|---|
| `--session SESSION_ID` | Session to append this query to — falls back per the resolution order above |
| `--format table\|json\|nl` | Output format (default `table`) |
| `--top-k N` | Max results (default 10) |
| `--verbose` / `-v` | Show tool-call arguments in the status line |
| `--log` / `-l` | Also print each tool call and result, each sub-query and each quality-metric score on its own persistent line |
| `--log-limit N` | Truncation length for verbose/log output (default 80) |

`data search` options: `--type entity|fact` (repeatable), `--mode keyword|semantic`, `--top-k N`, `--format table|json`.

`data extract` options: `--query QUESTION` (repeatable), `--source NAME`, `--model MODEL` (default `gpt-4o`), plus `--verbose`/`-v`, `--log`/`-l`, `--log-limit`.

```bash
blue-userdb --database alice data query "What jobs are suitable for me?" --format nl
blue-userdb data extract "Alice joined Acme Corp in 2019 as a data scientist." \
    --query "What role does Alice have?"
```

### `blue-userdb data source`

| Command | Description |
|---|---|
| `blue-userdb data source list [--show-detailed] [--format]` | List the sources added to the database (KG `SOURCE` nodes), with the id `source remove` accepts |
| `blue-userdb data source add FILE [options]` | Register a file as a source — always ingested into `external_documents`; optionally extracted into the KG |
| `blue-userdb data source remove NAME [--yes]` | Remove a source by name or id: its document leaves search and query answers; facts extracted from it are kept |

`source add` options: `--query QUESTION` (repeatable — presence triggers Type 2), `--name`, `--description`, `--original`.

```bash
blue-userdb data source add resume.txt                                  # Type 1
blue-userdb data source add resume.txt --query "What skills?"            # Type 2
```

---

## `blue-userdb schema`

Schema management. All `schema` commands require an active database.

| Command | Description |
|---|---|
| `blue-userdb schema list [--format]` | List classes, relations, and properties |
| `blue-userdb schema import FILE` | Import a schema (idempotent) |
| `blue-userdb schema export [-o FILE]` | Export the schema as JSON |
| `blue-userdb schema search QUERY [--type]` | Search classes, relations, and properties |
`schema search` options: `--type class|relation|property` (repeatable), `--mode keyword|semantic`, `--top-k N`, `--format table|json`.

---

## `blue-userdb metadata`

User metadata for agents acting on your behalf — dot-path addressed, backed by [`data/metadata_schema.json`](../lib/src/blue_data_user_source/data/metadata_schema.json).

| Command | Description |
|---|---|
| `blue-userdb metadata list [PATH...] [-r\|--recursive] [--format table\|json]` | List categories, or the fields under a path; `--recursive` flattens everything below the path into `key = value` rows |
| `blue-userdb metadata get PATH...` | Get a single value (dotted path given as space-separated segments) |
| `blue-userdb metadata set PATH... VALUE` | Set a value — all but the last argument are path segments |
| `blue-userdb metadata delete PATH... [--yes]` | Delete a key |

Values passed to `set` are parsed as JSON when possible (numbers, booleans, `null`, arrays, objects), otherwise kept as a plain string.

```bash
blue-userdb metadata list                                        # top-level categories with counts
blue-userdb metadata list identity                                 # fields under "identity"
blue-userdb metadata list --recursive                              # every set + unset schema field, flattened
blue-userdb metadata set identity name "Alice"
blue-userdb metadata set preferences verbosity brief
blue-userdb metadata set availability preferred_channel email
blue-userdb metadata get privacy consent_level
blue-userdb metadata delete identity pronouns
```

Categories: `identity` (name, pronouns, locale, timezone), `preferences` (communication_style, verbosity, language), `availability` (working_hours, preferred_channel, out_of_office, by_topic), `privacy` (data_sharing_preference, sensitive_categories, retention_days, consent_level).

---

## `blue-userdb contact`

Contact methods for agents to reach you — dot-path addressed by protocol/name/field, backed by [`data/contact_schema.json`](../lib/src/blue_data_user_source/data/contact_schema.json).

| Command | Description |
|---|---|
| `blue-userdb contact list [PATH...] [-r\|--recursive] [--format table\|json]` | List protocols, or named entries under a protocol, or fields of one entry |
| `blue-userdb contact get PROTOCOL NAME [FIELD...]` | Get an entry or a specific field |
| `blue-userdb contact set PROTOCOL NAME FIELD... VALUE` | Set a field on an entry |
| `blue-userdb contact add PROTOCOL NAME [--preference N]` | Create a named entry (set its remaining fields with `contact set` afterwards) |
| `blue-userdb contact remove PROTOCOL NAME [--yes]` | Remove a named entry |

```bash
blue-userdb contact list                                    # protocols with entry counts
blue-userdb contact add email work
blue-userdb contact set email work address alice@example.com
blue-userdb contact set email work inbound_provider stdio
blue-userdb contact list email --recursive
blue-userdb contact get email work address
blue-userdb contact remove email work
```

Protocols: `email`, `webhook`, `sms`, `messaging`, `enterprise`, `notification`, `session`, `stdio` — see [api-reference.md](api-reference.md#contactmanager--contactmethod) for detail keys per protocol. Only `stdio`, `email` and `webhook` have a transport in this release. The rest can be recorded with this command, but are never used to contact the user — contact selection skips them; `contact list` marks them "Recorded only".

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
