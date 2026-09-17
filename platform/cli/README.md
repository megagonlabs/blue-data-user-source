# udb CLI

Command-line interface for the user database — a per-user knowledge store with natural language querying.

See [docs/cli.md](../../docs/cli.md) for the complete command reference, including the `metadata` and `contact` groups not covered below. This README covers installation, a quick start, and running this package's tests.

## Installation

The library is not yet published to PyPI. Install both packages from source:

```bash
# 1. Install the library
cd lib && pip install -e . && cd ..

# 2. Install the CLI
cd platform/cli && pip install -e .
```

`click` and `rich` are pulled in automatically as CLI dependencies.

Set your OpenAI API key if you plan to use extraction or query commands:

```bash
export OPENAI_API_KEY=sk-...
```

## Quick start

```bash
# Create a database (auto-selects it — saves to ~/.udb/.selected.database)
udb database create alice

# Register a file as a data source (Type 1)
udb data source add resume.txt

# Extract and store specific attributes (Type 2)
udb data source add resume.txt \
  --query "What skills does the user have?" \
  --query "What is the user's most recent job title?"

# Query — Rich table (default)
udb data query "What jobs are suitable for me?"

# Query — natural language answer
udb data query "What jobs are suitable for me?" --format nl

# Query — raw JSON
udb data query "What jobs are suitable for me?" --format json

# Sessions — group multiple queries into one conversation
udb session start                              # creates and selects a session
udb data query "What jobs are suitable for me?" # continues the selected session
udb data query "What about remote roles?"       # same session — has context from the previous query
udb session show                                # see the session's queries and interactions
udb session end                                 # done — clears the selection
```

## Commands

### Global options

```
udb [--profile NAME] [--database NAME] [--session ID] [--data-dir DIR]
    [--schema-path PATH] [--metadata-schema-path PATH] [--contact-schema-path PATH]
    COMMAND
```

| Option | Profile parameter | Default | Description |
|---|---|---|---|
| `--profile NAME` | — (`BLUE_DATA_PROFILE`) | the selection in `~/.udb/.selected.profile` | Configuration profile |
| `--database NAME` | `BLUE_DATA_USER_SOURCE_DATABASE` | — | Active database (user) name |
| `--session ID` | `BLUE_DATA_USER_SOURCE_SESSION` | the selection in `~/.udb/.selected.session` | Session id for query context |
| `--data-dir DIR` | `BLUE_DATA_USER_SOURCE_DATA_DIR` | `~/.udb` | Directory where database files are stored |
| `--schema-path PATH` | `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | — | Path to `schema.json` for KB schema seeding |
| `--metadata-schema-path PATH` | `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` | packaged `metadata_schema.json` | Path to the metadata schema |
| `--contact-schema-path PATH` | `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` | packaged `contact_schema.json` | Path to the contact schema |

Each option falls back to the selected profile; exporting the environment variable of the same name still overrides the profile. See [Profiles and configuration](#profiles-and-configuration).

### Profiles and configuration

A **profile** is a named set of configuration values — API keys, models, backend choices — stored as one section of `~/.udb/.profiles`. Everything the CLI reads comes from the selected profile, so switching environments is one command rather than a shell full of exports.

The first `udb` command creates a `default` profile and selects it, so there is nothing to set up before the CLI works:

```bash
$ udb profile config                  # walk through the required parameters
$ udb profile inspect                 # every value, and where it came from
```

`add` is for additional profiles:

```bash
$ udb profile add staging
$ udb profile select staging
$ udb profile config                  # configures staging, now that it is selected
```

`udb profile config` has three forms — no arguments walks every required parameter, `PARAM` prompts for one, `PARAM VALUE` sets one directly. Add `--profile NAME` to configure a profile other than the selected one.

**Precedence:** command option > environment variable > profile > default. `udb profile inspect` reports the winning tier for every parameter.

**Secrets** are never accepted as a command-line value — that would put them in your shell history — so `udb profile config OPENAI_API_KEY` always prompts. Enter the key to store it encoded, or `$OPENAI_API_KEY` to store a reference read from the environment at use. `~/.udb/.profiles` is written `0600` and `inspect` masks stored secrets.

> The encoded form is obfuscation, not encryption: anyone who can read the file can decode it. The file mode is the real protection, and the `$VAR` reference form keeps the secret off disk entirely.

| Parameter | Cast | Default | Asked by `config` |
|---|---|---|---|
| `OPENAI_API_KEY` | secret | — | ✓ |
| `ANTHROPIC_API_KEY` | secret | — | |
| `BLUE_DATA_LLM_PROVIDER` | str | `openai` | |
| `BLUE_DATA_LLM_MODEL` | str | `gpt-4o` | ✓ |
| `BLUE_DATA_CLI_FORMAT` | str | `table` | |
| `BLUE_DATA_CLI_LOG_LIMIT` | int | `80` | |
| `BLUE_DATA_USER_SOURCE_DATA_DIR` | directory | `~/.udb` | ✓ |
| `BLUE_DATA_USER_SOURCE_DATABASE` | str | — | ✓ |
| `BLUE_DATA_USER_SOURCE_SESSION` | str | — | |
| `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | file | — | |
| `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` | file | *packaged* | |
| `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` | file | *packaged* | |
| `BLUE_DATA_USER_SOURCE_LLM_MODEL` | str | *inherits* | |
| `BLUE_DATA_USER_SOURCE_EXTRACTION_LLM_MODEL` | str | *inherits* | |
| `BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL` | str | *inherits* | |
| `BLUE_DATA_USER_SOURCE_KB_BACKEND` | str | `file` | |
| `BLUE_DATA_USER_SOURCE_KB_SEARCH_MODE` | str | `bm25` | |
| `BLUE_DATA_USER_SOURCE_KB_VECTOR_BACKEND` | str | `file` | |
| `BLUE_DATA_USER_SOURCE_KB_EMBEDDING_MODEL` | str | `text-embedding-3-small` | |
| `BLUE_DATA_USER_SOURCE_DOC_BACKEND` | str | `file` | |
| `BLUE_DATA_USER_SOURCE_NEO4J_HOST` | str | `localhost` | |
| `BLUE_DATA_USER_SOURCE_NEO4J_PORT` | int | `7687` | |
| `BLUE_DATA_USER_SOURCE_NEO4J_USER` | str | `neo4j` | |

Each per-function model falls back to `BLUE_DATA_USER_SOURCE_LLM_MODEL`, then to `BLUE_DATA_LLM_MODEL` — so setting one value covers every command, and a single function can still be pinned to a different model. The `KB_*`, `DOC_*` and `NEO4J_*` parameters supply the defaults for `udb database create`, which has no `config set` to change them afterwards.

`BLUE_DATA_USER_SOURCE_HOME` (default `~/.udb`) is deliberately *not* a profile parameter: it is the directory the profiles themselves live in, so it can only be set in the environment.

| Command | Description |
|---|---|
| `udb profile add NAME` | Create an additional profile (`default` is created on first use) |
| `udb profile remove NAME [--confirm]` | Delete a profile and its configuration |
| `udb profile list [--format table\|json]` | List profiles, marking the selected one |
| `udb profile select NAME` | Set the default profile |
| `udb profile inspect [NAME] [--format table\|json]` | Show every value and the tier it came from; secrets masked |
| `udb profile config [PARAM [VALUE]] [--profile NAME]` | Set configuration; secrets always prompt |

`--database` can also be set persistently with `udb database select NAME`, which writes to `~/.udb/.selected.database`.

```bash
export BLUE_DATA_USER_SOURCE_DATABASE=alice
udb data query "jobs suitable for me"
```

---

### `udb database`

Manage user databases.

| Command | Description |
|---|---|
| `udb database list` | List all registered databases |
| `udb database create NAME` | Create a new database |
| `udb database delete NAME` | Delete a database and all its data |
| `udb database select NAME` | Set the active database |
| `udb database search KEYWORD` | Search databases by name keyword |
| `udb database reset` | Clear KB data for the active database and reseed the schema |
| `udb database config show` | Show the database configuration |
```bash
udb database create alice
udb database select alice
udb database list
udb database search ali
udb database reset --yes
udb database config show
udb database delete alice --yes
```

`database create` options:

| Option | Default | Description |
|---|---|---|
| `--kb-backend` | `file` | KB backend: `memory`, `file`, or `neo4j` |
| `--neo4j-host` | `localhost` | Neo4j host (neo4j backend only) |
| `--neo4j-port` | `7687` | Neo4j bolt port |
| `--neo4j-user` | `neo4j` | Neo4j username |
| `--neo4j-password` | — | Neo4j password (required for neo4j backend) |
| `--doc-backend` | `file` | Vector backend for per-session interaction transcripts: `memory` or `file` |

```bash
# File backend (default)
udb database create alice

# Neo4j backend
udb database create alice \
  --kb-backend neo4j \
  --neo4j-host db.example.com \
  --neo4j-port 7687 \
  --neo4j-user neo4j \
  --neo4j-password secret
```

---

### `udb session`

A session groups the queries and clarification interactions of one conversation. `udb data query` uses whatever session is selected (or auto-creates one if none is — see below), the same way `udb database select` works for databases.

| Command | Description |
|---|---|
| `udb session start` | Create a session and select it |
| `udb session select ID` | Set the active session |
| `udb session end [ID]` | End a session (defaults to the selected one); clears the selection if it matches |
| `udb session list` | List sessions |
| `udb session show [ID]` | Show a session's queries and interactions (defaults to the selected one) |

```bash
udb session start
udb data query "What jobs are suitable for me?"
udb session show
udb session list
udb session end
```

**Resolution order** for the session used by `udb data query`: `--session` flag → `BLUE_DATA_USER_SOURCE_SESSION` env var → `.selected.session` file. Unlike database selection, an unresolved session is **not** an error — the query auto-creates a new session and that session is then written to `.selected.session`, so the next query continues it automatically.

---

### `udb data`

Instance data management. All `data` commands require an active database (via `--database` or `udb database select`).

#### `udb data list`

List all entities, property values, and facts in the database.

```
udb data list [--show-provenance] [--format (table|json)]
```

#### `udb data query`

Execute a natural-language query against the database's knowledge graph.

```
udb data query TEXT [--session SESSION_ID] [--format (table|json|nl)] [--top-k N]
                     [--include-expanded] [--verbose] [--log] [--log-limit N]
```

| Option | Description |
|---|---|
| `--session SESSION_ID` | Session to append this query to. Falls back to the selected session (`udb session select`/`start`), then auto-creates one if neither is set — see [`udb session`](#udb-session) |
| `--format` | `table` (default) · `json` · `nl` |
| `--top-k N` | Maximum results (default: 10) |
| `--include-expanded` | Also print the per-sub-question queries and their raw results, below the main answer |
| `--verbose`, `-v` | Show tool call arguments in the status line while the query runs |
| `--log`, `-l` | Log each tool call and result on its own line |
| `--log-limit N` | Truncation limit for logged values (default: 80) |

```bash
udb --database alice data query "What skills does this user have?"
udb --database alice data query "What jobs are suitable for me?" --format nl
```

#### `udb data search`

Search entities and facts by keyword or semantic similarity.

```
udb data search QUERY [--type entity|fact] [--mode keyword|semantic] [--top-k N] [--format (table|json)]
```

#### `udb data import`

Import instance data previously produced by `udb data export` (KG only). Schema must already exist — run `udb schema import` first.

```
udb data import INPUT_FILE
```

#### `udb data export`

Export the database's instance data (entities, facts, property values) as JSON. Does not include schema — use `udb schema export` for that.

```
udb data export [--show-provenance] [--output FILE]
```

#### `udb data extract`

Extract entities, facts, and property values from free text using an LLM.

Requires `pip install 'blue-data-kb-source[openai]'` and `OPENAI_API_KEY`.

```
udb data extract TEXT [--query QUESTION]... [--source NAME] [--model MODEL]
```

```bash
udb data extract "Alice joined Acme Corp in 2019 as a data scientist." \
  --query "What role does Alice have?"
```

---

### `udb data source`

Manage data sources associated with the active database.

| Command | Description |
|---|---|
| `udb data source list` | List registry sources and KG SOURCE nodes; KG-only entries are marked `(*)` |
| `udb data source add FILE` | Register a file (.txt/.pdf/.docx) as a source — always parsed, chunked, and embedded into the shared `external_documents` DocumentDataSource, and optionally extracted into the KG |
| `udb data source remove NAME` | Remove a source, keeping its KB data |
**Type 1 — register + ingest for later search**

```bash
udb data source add resume.txt
# Ingested source: resume.txt
```

**Type 2 — also extract and store attributes in the KG**

```bash
udb data source add resume.txt \
  --query "What skills does the user have?" \
  --query "Does the user prefer remote work?"
# Ingested source: resume.txt (2 queries extracted to KB)
```

**Listing sources**

```bash
udb data source list
```

Sources that were added to the knowledge graph but subsequently removed from the registry are shown with a `(*)` marker.

---

### `udb schema`

Schema management. All `schema` commands require an active database.

| Command | Description |
|---|---|
| `udb schema list` | List classes, relations, and properties |
| `udb schema import INPUT_FILE` | Import a schema (idempotent) |
| `udb schema export` | Export the schema as JSON |
| `udb schema search QUERY` | Search classes, relations, and properties |
```bash
udb schema list
udb schema export --output schema.json
udb schema import schema.json
udb schema search "employment" --type class
```

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Error — message printed to stderr |
| 2 | Bad arguments (Click) |

---

## Storage layout

Data is persisted under `~/.udb/` by default:

```
~/.udb/
├── .profiles                  # configuration profiles (mode 0600, written by 'udb profile config')
├── .selected.profile          # active profile name (written by 'udb profile select')
├── .selected.database         # active database name (written by 'udb database select'/'create')
├── .selected.session           # active session id (written by 'udb session select'/'start', and auto-created sessions)
├── registry.json              # outer DataRegistry store (databases + source properties)
├── registries/
│   └── alice.json             # per-user DataRegistry store (sources registered for alice)
└── sources/
    └── alice/
        ├── alice.json         # per-user knowledge graph (file KB backend)
        ├── metadata.json      # user metadata
        ├── contacts.json      # user contact methods
        ├── sessions.json      # session / query / interaction records
        └── sessions/          # per-session interaction transcripts (file vector backend, --doc-backend file)
```

Use `--data-dir` to store databases elsewhere:

```bash
udb --data-dir /tmp/demo database create alice
udb --data-dir /tmp/demo --database alice data source add resume.txt --query "What skills?"
udb --data-dir /tmp/demo --database alice data query "jobs suitable for me"
```

---

## Running tests

```bash
cd platform/cli
pytest
```

The CLI test suite covers command parsing and output formatting with an all-memory backend — no API key or network access required.
