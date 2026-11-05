# blue-userdb CLI

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

Set your LLM provider's API key if you plan to use extraction or query commands (OpenAI by default; for Claude, set `BLUE_DATA_LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`):

```bash
export OPENAI_API_KEY=sk-...
```

## Quick start

```bash
# Create a database (auto-selects it — saves to ~/.blue-userdb/.selected.database)
blue-userdb database create alice

# Register a file as a data source (Type 1)
blue-userdb data source add data/resume.txt

# Extract and store specific attributes (Type 2)
blue-userdb data source add data/resume.txt \
  --query "What skills does the user have?" \
  --query "What is the user's most recent job title?"

# Query — Rich table (default)
blue-userdb data query "What jobs are suitable for me?"

# Query — natural language answer
blue-userdb data query "What jobs are suitable for me?" --format nl

# Query — raw JSON
blue-userdb data query "What jobs are suitable for me?" --format json

# Sessions — group multiple queries into one conversation
blue-userdb session start                              # creates and selects a session
blue-userdb data query "What jobs are suitable for me?" # continues the selected session
blue-userdb data query "What about remote roles?"       # same session — has context from the previous query
blue-userdb session show                                # see the session's queries and interactions
blue-userdb session end                                 # done — clears the selection
```

## Commands

### Global options

```
blue-userdb [--profile NAME] [--database NAME] [--session ID] [--data-dir DIR]
    [--schema-path PATH] [--metadata-schema-path PATH] [--contact-schema-path PATH]
    COMMAND
```

| Option | Profile parameter | Default | Description |
|---|---|---|---|
| `--profile NAME` | — (`BLUE_DATA_PROFILE`) | the selection in `~/.blue-userdb/.selected.profile` | Configuration profile |
| `--database NAME` | `BLUE_DATA_USER_SOURCE_DATABASE` | the selection in `~/.blue-userdb/.selected.database`, then the profile | Active database (user) name |
| `--session ID` | `BLUE_DATA_USER_SOURCE_SESSION` | the database's selection in `~/.blue-userdb/.selected.session.<database>` | Session id for query context |
| `--data-dir DIR` | `BLUE_DATA_USER_SOURCE_DATA_DIR` | `~/.blue-userdb` | Directory where database files are stored |
| `--schema-path PATH` | `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | — | Path to `schema.json` for KB schema seeding |
| `--metadata-schema-path PATH` | `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` | packaged `metadata_schema.json` | Path to the metadata schema |
| `--contact-schema-path PATH` | `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` | packaged `contact_schema.json` | Path to the contact schema |

Each option falls back to the selected profile; exporting the environment variable of the same name still overrides the profile. See [Profiles and configuration](#profiles-and-configuration).

### Profiles and configuration

A **profile** is a named set of configuration values — API keys, models, backend choices — stored as one section of `~/.blue-userdb/.profiles`. Everything the CLI reads comes from the selected profile, so switching environments is one command rather than a shell full of exports.

The first `blue-userdb` command creates a `default` profile and selects it, so there is nothing to set up before the CLI works:

```bash
$ blue-userdb profile config                  # walk through the required parameters
$ blue-userdb profile inspect                 # every value, and where it came from
```

`add` is for additional profiles:

```bash
$ blue-userdb profile add staging
$ blue-userdb profile select staging
$ blue-userdb profile config                  # configures staging, now that it is selected
```

`blue-userdb profile config` has three forms — no arguments walks every required parameter, `PARAM` prompts for one, `PARAM VALUE` sets one directly. Add `--profile NAME` to configure a profile other than the selected one.

**Precedence:** command option > environment variable > profile > default. The database is the one exception: the selection written by `database select` / `database create` sits between the environment variable and the profile — **`--database` > environment variable > `.selected.database` > profile** — so selecting a database works even when the profile names one. `blue-userdb profile inspect` reports the winning tier for every parameter.

**Secrets** are never accepted as a command-line value — that would put them in your shell history — so `blue-userdb profile config OPENAI_API_KEY` always prompts. Enter the key to store it encoded, or `$OPENAI_API_KEY` to store a reference read from the environment at use. `~/.blue-userdb/.profiles` is written `0600` and `inspect` masks stored secrets.

> The encoded form is obfuscation, not encryption: anyone who can read the file can decode it. The file mode is the real protection, and the `$VAR` reference form keeps the secret off disk entirely.

| Parameter | Cast | Default | Asked by `config` |
|---|---|---|---|
| `OPENAI_API_KEY` | secret | — | ✓ |
| `ANTHROPIC_API_KEY` | secret | — | |
| `BLUE_DATA_LLM_PROVIDER` | str | — (blank) | |
| `BLUE_DATA_LLM_MODEL` | str | — (the provider's default) | |
| `BLUE_DATA_CLI_FORMAT` | str | `table` | |
| `BLUE_DATA_CLI_LOG_LIMIT` | int | `80` | |
| `BLUE_DATA_USER_SOURCE_DATA_DIR` | directory | `~/.blue-userdb` | ✓ |
| `BLUE_DATA_USER_SOURCE_DATABASE` | str | — | ✓ |
| `BLUE_DATA_USER_SOURCE_SESSION` | str | — | |
| `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | file | — | |
| `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` | file | *packaged* | |
| `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` | file | *packaged* | |
| `BLUE_DATA_USER_SOURCE_LLM_MODEL` | str | *see below* | |
| `BLUE_DATA_USER_SOURCE_EXTRACTION_LLM_MODEL` | str | *inherits* | |
| `BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL` | str | *inherits* | |
| `BLUE_DATA_USER_SOURCE_KB_BACKEND` | str | `file` | |
| `BLUE_DATA_USER_SOURCE_KB_SEARCH_MODE` | str | `bm25` | |
| `BLUE_DATA_USER_SOURCE_KB_VECTOR_BACKEND` | str | `file` | |
| `BLUE_DATA_USER_SOURCE_KB_EMBEDDING_MODEL` | str | `text-embedding-3-small` | |
| `BLUE_DATA_USER_SOURCE_DOC_BACKEND` | str | `file` | |
| `BLUE_DATA_USER_SOURCE_DOC_SEARCH_MODE` | str | `vector` | |
| `BLUE_DATA_USER_SOURCE_DOC_EMBEDDING_MODEL` | str | `openai` | |
| `BLUE_DATA_USER_SOURCE_NEO4J_HOST` | str | `localhost` | |
| `BLUE_DATA_USER_SOURCE_NEO4J_PORT` | int | `7687` | |
| `BLUE_DATA_USER_SOURCE_NEO4J_USER` | str | `neo4j` | |
| `BLUE_DATA_USER_SOURCE_NEO4J_PASSWORD` | secret | — | |

blue-userdb's LLM calls (query reasoning and the KB's answering agent, onboarding and NL synthesis, `data extract` and `data source add --query`) go through LiteLLM to the `BLUE_DATA_LLM_PROVIDER` provider: blank means `openai` (`OPENAI_API_KEY`), and `anthropic` uses `ANTHROPIC_API_KEY`. Each per-function model falls back to `BLUE_DATA_USER_SOURCE_LLM_MODEL` — so setting one value covers every command, and a single function can still be pinned to a different model — then to the family's `BLUE_DATA_LLM_MODEL`, and last to the provider's default: `gpt-4o` for `openai`, `claude-opus-4-8` for `anthropic`. `profile inspect` shows that default, with the source `openai default` or `anthropic default`, for a model left unset. Document embeddings stay on OpenAI: a database created with the default `openai` embedding needs `OPENAI_API_KEY` under any provider. The `KB_*`, `DOC_*` and `NEO4J_*` parameters supply the defaults for `blue-userdb database create`, which has no `config set` to change them afterwards.

`BLUE_DATA_USER_SOURCE_HOME` (default `~/.blue-userdb`) is deliberately *not* a profile parameter: it is the directory the profiles themselves live in, so it can only be set in the environment.

| Command | Description |
|---|---|
| `blue-userdb profile add NAME` | Create an additional profile (`default` is created on first use) |
| `blue-userdb profile remove NAME [--confirm]` | Delete a profile and its configuration |
| `blue-userdb profile list [--format table\|json]` | List profiles, marking the selected one |
| `blue-userdb profile select NAME` | Set the default profile |
| `blue-userdb profile inspect [NAME] [--format table\|json]` | Show every value and the tier it came from; secrets masked |
| `blue-userdb profile config [PARAM [VALUE]] [--profile NAME]` | Set configuration; secrets always prompt |

`--database` can also be set persistently with `blue-userdb database select NAME`, which writes to `~/.blue-userdb/.selected.database`.

```bash
export BLUE_DATA_USER_SOURCE_DATABASE=alice
blue-userdb data query "jobs suitable for me"
```

---

### `blue-userdb database`

Manage user databases.

| Command | Description |
|---|---|
| `blue-userdb database list` | List all registered databases |
| `blue-userdb database create NAME` | Create a new database |
| `blue-userdb database delete NAME` | Delete a database and all its data |
| `blue-userdb database select NAME` | Set the active database |
| `blue-userdb database search KEYWORD` | Search databases by name keyword |
| `blue-userdb database onboard` | Ask the user onboarding questions to seed KB data and metadata |
| `blue-userdb database reset` | Clear the active database's KB data, ingested documents, metadata, contacts and sessions, and reseed the schemas |
| `blue-userdb database config show` | Show the database configuration |
```bash
blue-userdb database create alice
blue-userdb database select alice
blue-userdb database list
blue-userdb database search ali
blue-userdb database reset --yes
blue-userdb database config show
blue-userdb database delete alice --yes
```

`database create` options:

| Option | Default | Description |
|---|---|---|
| `--kb-backend` | `file` | KB backend: `memory`, `file`, or `neo4j` |
| `--neo4j-host` | `localhost` | Neo4j host (neo4j backend only) |
| `--neo4j-port` | `7687` | Neo4j bolt port |
| `--neo4j-user` | `neo4j` | Neo4j username |
| _(password)_ | the profile's `BLUE_DATA_USER_SOURCE_NEO4J_PASSWORD` | Neo4j password (required for `neo4j` backend). Not a command-line option, so it stays out of shell history: set it with `blue-userdb profile config BLUE_DATA_USER_SOURCE_NEO4J_PASSWORD` (prompts) or export that variable. The password is not stored with the user: each command reads it from that profile value or variable, and so must any other process opening the user (the MCP and REST servers need the variable set) |
| `--kb-vector-backend` | `file` | Vector store for KB semantic search: `memory` or `file` (`--kb-search-mode semantic` only) |
| `--kb-embedding-model` | `text-embedding-3-small` | OpenAI embedding model for KB semantic search (`--kb-search-mode semantic` only) |
| `--metadata-onboard` / `--no-metadata-onboard` | on | Include structured metadata questions in onboarding (KB questions are always asked) |
| `--doc-backend` | `file` | Vector backend for the user's documents (session transcripts, added files): `memory` or `file` |
| `--doc-search-mode` | `vector` | How those documents are searched: `vector` (by meaning), `hybrid` (meaning and keywords) or `bm25` (keywords). `bm25`'s index lasts only for the command that added the documents, so later commands find nothing |
| `--doc-embedding-model` | `openai` | `openai` (`text-embedding-3-small`; needs `OPENAI_API_KEY`) or `dummy` (a hash, no API calls; only with `--doc-search-mode bm25`) |

```bash
# File backend (default)
blue-userdb database create alice

# Neo4j backend
blue-userdb profile config BLUE_DATA_USER_SOURCE_NEO4J_PASSWORD   # prompts; never on the command line
blue-userdb database create alice \
  --kb-backend neo4j \
  --neo4j-host db.example.com \
  --neo4j-port 7687 \
  --neo4j-user neo4j
```

---

### `blue-userdb session`

A session groups the queries and clarification interactions of one conversation. `blue-userdb data query` uses whatever session is selected (or auto-creates one if none is — see below), the same way `blue-userdb database select` works for databases.

| Command | Description |
|---|---|
| `blue-userdb session start` | Create a session and select it |
| `blue-userdb session select ID` | Set the active session |
| `blue-userdb session end [ID]` | End a session (defaults to the selected one); clears the selection if it matches |
| `blue-userdb session list` | List sessions |
| `blue-userdb session show [ID]` | Show a session's queries and interactions (defaults to the selected one) |

```bash
blue-userdb session start
blue-userdb data query "What jobs are suitable for me?"
blue-userdb session show
blue-userdb session list
blue-userdb session end
```

**Resolution order** for the session used by `blue-userdb data query`: `--session` flag → `BLUE_DATA_USER_SOURCE_SESSION` env var → the database's `.selected.session.<database>` file. Unlike database selection, an unresolved session is **not** an error — the query auto-creates a new session and that session is then written to `.selected.session`, so the next query continues it automatically.

---

### `blue-userdb data`

Instance data management. All `data` commands require an active database (via `--database` or `blue-userdb database select`).

#### `blue-userdb data list`

List all entities, property values, and facts in the database.

```
blue-userdb data list [--show-provenance] [--format (table|json)]
```

#### `blue-userdb data query`

Execute a natural-language query against the database's knowledge graph.

```
blue-userdb data query TEXT [--session SESSION_ID] [--format (table|json|nl)] [--top-k N]
                     [--max-subqueries N] [--max-kb-turns N] [--max-rounds N] [--model MODEL]
                     [--include-expanded] [--verbose] [--log] [--log-limit N]
```

| Option | Description |
|---|---|
| `--session SESSION_ID` | Session to append this query to. Falls back to the selected session (`blue-userdb session select`/`start`), then auto-creates one if neither is set — see [`blue-userdb session`](#blue-userdb-session) |
| `--format` | `table` (default) · `json` · `nl` |
| `--top-k N` | Max chunks taken from each document store (`external_documents`, `session_content`) per sub-question (default 5); the knowledge graph has no result limit |
| `--max-subqueries N` | Most sub-questions added to the query, each answered by the KB's agent; `0` answers the query alone (default: as many as needed, at most 5) |
| `--max-kb-turns N` | Most tool-calling turns of the KB's agent per sub-question (default 25) |
| `--max-rounds N` | Most rounds of clarification questions (default 3). Asked on the terminal only when stdin is one; otherwise over another contact method, or not at all |
| `--model MODEL` | Model for the reasoning and the KB's agent, of the `BLUE_DATA_LLM_PROVIDER` provider (default: the profile's `BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL`, else the provider's default) |
| `--include-expanded` | Also print the per-sub-question queries and their raw results, below the main answer |
| `--verbose`, `-v` | Show tool call arguments in the status line while the query runs |
| `--log`, `-l` | Log each tool call and result on its own line |
| `--log-limit N` | Truncation limit for logged values (default: 80) |

```bash
blue-userdb --database alice data query "What skills does this user have?"
blue-userdb --database alice data query "What jobs are suitable for me?" --format nl
```

#### `blue-userdb data search`

Search entities and facts by keyword or semantic similarity.

```
blue-userdb data search QUERY [--type entity|fact] [--mode keyword|semantic] [--top-k N] [--format (table|json)]
```

#### `blue-userdb data import`

Import instance data previously produced by `blue-userdb data export` (KG only). Schema must already exist — run `blue-userdb schema import` first.

```
blue-userdb data import INPUT_FILE
```

#### `blue-userdb data export`

Export the database's instance data (entities, facts, property values) as JSON. Does not include schema — use `blue-userdb schema export` for that.

```
blue-userdb data export [--show-provenance] [--output FILE]
```

#### `blue-userdb data extract`

Extract entities, facts, and property values from free text using an LLM.

Requires the `BLUE_DATA_LLM_PROVIDER` provider's API key (`OPENAI_API_KEY` by default).

```
blue-userdb data extract TEXT [--query QUESTION]... [--source NAME] [--model MODEL]
```

```bash
blue-userdb data extract "Alice joined Acme Corp in 2019 as a data scientist." \
  --query "What role does Alice have?"
```

---

### `blue-userdb data source`

Manage data sources associated with the active database.

| Command | Description |
|---|---|
| `blue-userdb data source list` | List the sources added to the database, with the id `source remove` accepts |
| `blue-userdb data source add FILE [--effort low\|medium\|high]` | Register a file (.txt/.pdf/.docx) as a source — always parsed, chunked, and embedded into the shared `external_documents` DocumentDataSource, and optionally extracted into the KG |
| `blue-userdb data source remove NAME` | Remove a source by name or id: its document leaves search and query answers; facts extracted from it are kept |
**Type 1 — register + ingest for later search**

```bash
blue-userdb data source add data/resume.txt
# Ingested source: data/resume.txt
```

**Type 2 — also extract and store attributes in the KG**

```bash
blue-userdb data source add data/resume.txt \
  --query "What skills does the user have?" \
  --query "Does the user prefer remote work?"
# Ingested source: data/resume.txt (2 queries extracted to KB)
```

Adding a file that is already a source, as the Type 2 step does here, updates that source instead of adding a second one: its chunks are replaced by the new ingest (so an edited file is picked up), and the extraction is recorded under it. A file is the same source whatever spelling of its path you use, and two files with the same name in different directories are two sources. If the new ingest fails, the old document stays. The same file under another `--name` is another source.

**Listing sources**

```bash
blue-userdb data source list
```

Each source is listed with its id; `data source remove` takes the name or the id, and needs the id when two sources share a name.

---

### `blue-userdb schema`

Schema management. All `schema` commands require an active database.

| Command | Description |
|---|---|
| `blue-userdb schema list` | List classes, relations, and properties |
| `blue-userdb schema import INPUT_FILE` | Import a schema (idempotent) |
| `blue-userdb schema export` | Export the schema as JSON |
| `blue-userdb schema search QUERY` | Search classes, relations, and properties |
```bash
blue-userdb schema list
blue-userdb schema export --output schema.json
blue-userdb schema import schema.json
blue-userdb schema search "employment" --type class
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

Data is persisted under `~/.blue-userdb/` by default:

```
~/.blue-userdb/
├── .profiles                  # configuration profiles (mode 0600, written by 'blue-userdb profile config')
├── .selected.profile          # active profile name (written by 'blue-userdb profile select')
├── .selected.database         # active database name (written by 'blue-userdb database select'/'create')
├── .selected.session.alice     # alice's active session id (written by 'blue-userdb session select'/'start', and auto-created sessions; removed by 'database reset')
├── registry.json              # outer DataRegistry store (databases + source properties)
├── registries/
│   └── alice.json             # per-user DataRegistry store (sources registered for alice)
└── sources/
    └── alice/
        ├── alice.json         # per-user knowledge graph (file KB backend)
        ├── metadata.json      # user metadata
        ├── contacts.json      # user contact methods
        ├── sessions.json      # session / query / interaction records
        ├── kb_search_index/   # the knowledge graph's BM25 index (--kb-search-mode bm25, the default)
        ├── kb_vectors/        # its vector index instead (--kb-search-mode semantic)
        ├── sessions/          # session transcripts (--doc-backend file): vector store, and transcripts/<session id>/*.txt
        └── external_documents/  # chunks of added files (vector store)
```

Each JSON store has a `<file>.lock` beside it, and the knowledge graph a `.alice.lock`: cross-process write locks, removed with the user.

Use `--data-dir` to store databases elsewhere:

```bash
blue-userdb --data-dir /tmp/demo database create alice
blue-userdb --data-dir /tmp/demo --database alice data source add data/resume.txt --query "What skills?"
blue-userdb --data-dir /tmp/demo --database alice data query "jobs suitable for me"
```

---

## Running tests

```bash
cd platform/cli
pytest
```

The CLI test suite covers command parsing and output formatting with an all-memory backend — no API key or network access required.
