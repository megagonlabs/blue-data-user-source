# udb CLI

Command-line interface for the user database — a per-user knowledge store with natural language querying.

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
# Create a database
udb database create alice

# Select the active database (saves to ~/.udb/.selected.database)
udb database select alice

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
```

## Commands

### Global options

```
udb [--database NAME] [--data-dir DIR] [--schema-path PATH] COMMAND
```

| Option | Env var | Default | Description |
|---|---|---|---|
| `--database NAME` | `UDB_DATABASE` | — | Active database (user) name |
| `--data-dir DIR` | `UDB_DATA_DIR` | `~/.udb` | Directory where database files are stored |
| `--schema-path PATH` | `UDB_SCHEMA_PATH` | — | Path to `schema.json` for KB schema seeding |

`--database` can also be set persistently with `udb database select NAME`, which writes to `~/.udb/.selected.database`.

```bash
export UDB_DATABASE=alice
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
| `udb database config show` | Show stored configuration for the active database |

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
| `--neo4j-uri` | — | Neo4j bolt URI (neo4j backend only) |
| `--neo4j-user` | — | Neo4j username |
| `--neo4j-password` | — | Neo4j password |

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
```

| Option | Description |
|---|---|
| `--session SESSION_ID` | Session ID for query context and user interaction |
| `--format` | `table` (default) · `json` · `nl` |
| `--top-k N` | Maximum results (default: 10) |

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
| `udb data source add FILE` | Register a file as a source and optionally ingest its content |
| `udb data source remove NAME` | Remove a source from the registry (KG data is preserved) |

**Type 1 — register source only**

```bash
udb data source add resume.txt
# Registered source: resume.txt
```

**Type 2 — extract and store attributes**

```bash
udb data source add resume.txt \
  --query "What skills does the user have?" \
  --query "Does the user prefer remote work?"
# Added source: resume.txt (2 queries)
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
| `udb schema list` | List classes, relations, and their properties |
| `udb schema import INPUT_FILE` | Import a schema (idempotent) |
| `udb schema export` | Export the schema as JSON |
| `udb schema search QUERY` | Search schema elements by keyword or semantic similarity |

```bash
udb schema list
udb schema export --output schema.json
udb schema import schema.json
udb schema search "employment" --type CLASS
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
├── .selected.database     # active database name (written by 'udb database select')
├── db.json                # user store (list of registered databases)
├── registries/
│   └── alice.json         # per-user DataRegistry (list of sources)
├── kb/
│   └── alice.json         # per-user knowledge graph (file backend)
└── sources/
    ├── alice.metadata.json
    └── alice.contacts.json
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
