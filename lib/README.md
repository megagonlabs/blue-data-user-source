# blue-data-user-source

Python library for UDb — a multi-user knowledge base with natural language querying, LLM-based extraction, and interactive data quality assurance.

Backed by [blue-data](../blue-data) and [blue-data-kb-source](../blue-data-kb-source).

## Requirements

- Python 3.10+
- OpenAI API key (used by the reasoning and extraction layers)

## Installation

The package is not yet published to PyPI. Install it directly from the local source:

```bash
cd lib
pip install -e .
```

## Development setup

```bash
cd lib
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

### Construct a multi-user source

`UserSource` takes a `props` dict with `"store"` (where to keep the user list) and an optional `"schema"` path:

```python
import asyncio
from blue_data_user_source import UserSource, FileSource

# File-backed (survives process restarts)
us = UserSource({
    "store": {"backend": "file", "path": "~/.udb/users.json"},
    "schema": "data/schema.json",   # optional — used when seeding/resetting users
})

# In-memory (useful for testing)
us = UserSource({"store": {"backend": "memory"}})
```

### Manage users

Each user has its own `DataRegistry` (backed by a separate JSONSource) that stores the KB source registration and any other sources added via imports:

```python
async def main() -> None:
    # Create user — builds registry + KB from scratch, seeds schema
    await us.create_user(
        "alice",
        registry_props={"backend": "file", "path": "~/.udb/registries/alice.json"},
        kb_props={"backend": "file", "directory": "~/.udb/kb"},
    )

    # Add user — connects to an existing registry that already has a KB registered
    us.add_user(
        "bob",
        registry_props={"backend": "file", "path": "~/.udb/registries/bob.json"},
    )

    print(us.list_users())       # ["alice", "bob"]

    # Reset — clear KB data + non-KB registry entries, reseed schema
    await us.reset_user("alice")

    # Remove from main store only (KB data kept)
    us.remove_user("alice")

    # Remove from main store AND wipe KB data
    await us.delete_user("bob")

asyncio.run(main())
```

### Import and query

```python
async def main() -> None:
    await us.create_user(
        "alice",
        registry_props={"backend": "file", "path": "~/.udb/registries/alice.json"},
        kb_props={"backend": "file", "directory": "~/.udb/kb"},
    )

    # Type 1 — register a file as a queryable source (no extraction)
    await us.import_source(FileSource("resume.txt"), database="alice")

    # Type 2 — extract and store specific knowledge using LLM extraction
    await us.import_source(
        FileSource("resume.txt"),
        database="alice",
        optional_properties={"queries": ["What skills does the user have?"]},
    )

    # Query — returns list[QueryResult]
    results = await us.execute_query("jobs suitable for me", database="alice")
    for r in results:
        print(r.query, "→", r.results)

    # Query — returns a natural language string
    answer = await us.execute_query(
        "jobs suitable for me",
        database="alice",
        optional_properties={"output_form": "nl"},
    )
    print(answer)

asyncio.run(main())
```

Set `OPENAI_API_KEY` before running:

```bash
export OPENAI_API_KEY=sk-...
```

## API

### `UserSource(props)`

Constructs a multi-user source from a props dict.

| prop | Type | Description |
|---|---|---|
| `store` | `dict` | JSONSource config for the user-list store: `{"backend": "memory"}` or `{"backend": "file", "path": "..."}` |
| `schema` | `str` | Default path to `schema.json` (optional); used as fallback when `schema_path` is not set in `kb_props` |

### User management

| method | Description |
|---|---|
| `add_user(name, registry_props)` | Connect to an existing registry that already has a KB registered |
| `create_user(name, registry_props, kb_props)` *(async)* | Build registry + KB from scratch and seed schema |
| `list_users()` | Return list of user names |
| `get_user(name)` | Return main-store entry for one user, or None |
| `remove_user(name)` | Remove user from main store; KB and registry data unchanged |
| `reset_user(name)` *(async)* | Wipe KB data + non-KB registry entries, then reseed schema |
| `delete_user(name)` *(async)* | `reset_user` + `remove_user` |

`registry_props` — JSONSource config for the user's own DataRegistry:

```python
{"backend": "file", "path": "~/.udb/registries/alice.json"}
{"backend": "memory"}
```

`kb_props` — KB backend config passed to `UserDataManager.initialize`:

```python
{"backend": "memory"}
{"backend": "file", "directory": "~/.udb/kb"}
{"backend": "neo4j", "uri": "bolt://localhost:7687", "username": "neo4j", "password": "..."}
# optional: include schema_path to override the UserSource-level default
{"backend": "file", "directory": "...", "schema_path": "custom_schema.json"}
```

### `import_source(source, database, optional_properties)`

Imports a data source into a user knowledge base.

- **Type 1** (no `queries`): registers the source location as a provenance node.
- **Type 2** (`queries` provided): fetches content from the source, passes it to the KB extraction engine, and writes extracted entities and facts.

| optional_property | Type | Description |
|---|---|---|
| `queries` | `list[str]` | Extraction queries — each drives one `import_text` call (Type 2) |

### `execute_query(query, database, optional_properties)`

Executes a natural language query. Contextualises and expands it via LLM, retrieves data from the KB, assesses completeness and freshness, and prompts the user for clarification when quality checks fail. Interaction responses are stored back into the KB.

Returns `list[QueryResult]` (default) or `str` when `output_form="nl"`.

| optional_property | Type | Description |
|---|---|---|
| `session` | `str` | Session ID for interaction context |
| `output_form` | `"json"` \| `"nl"` | `"json"` returns `list[QueryResult]`; `"nl"` returns a synthesized natural language string |
| `top_k` | `int` | Max KB results per sub-query (default: 10) |

### `list_data(database)` / `describe_data(database)`

Return raw data entries from the KB (`list[dict]`) or a natural language summary (`str`).

### `list_metadata(database, source_id=None)` / `describe_metadata(database, source_id=None)`

Return registered source nodes from the KB (`list[dict]`) or a natural language summary (`str`). Optionally filtered by `source_id`.

### `QueryResult`

```python
@dataclass
class QueryResult:
    query: str
    results: list[Any]
```

## KB backends

### Memory

Runs entirely in-process. Data is lost on exit — useful for testing and short-lived sessions.

```python
{"backend": "memory"}
```

### File (default for CLI)

Persists data to JSON files in a directory — one file per user database.

```python
{"backend": "file", "directory": "~/.udb/kb"}
```

### Neo4j

Persists data to a running Neo4j instance.

```python
{
    "backend": "neo4j",
    "uri": "bolt://localhost:7687",
    "username": "neo4j",
    "password": "password",
}
```

## Schema

The KB schema is defined in `data/schema.txt` (Cypher-like notation) and converted once to `data/schema.json`:

```bash
python tools/convert_schema.py \
    lib/src/blue_data_user_source/data/schema.txt \
    lib/src/blue_data_user_source/data/schema.json
```

The JSON file is consumed by `KBSource.import_database_schema` (entity and relation types) and `KBSource.add_is_subclass_of` (subclass edges).

## CLI

```
udb [--user NAME] [--data-dir DIR] [--schema-path PATH] COMMAND

Commands:
  query TEXT          Execute a query
  import FILE         Import a file
  user create NAME    Create a new user database
  user delete NAME    Delete a user database and its KB data
  user reset NAME     Clear KB data and reseed schema
  user ls             List all users
  user show data      Show data entries
  user show metadata  Show source metadata
```

User data is stored under `~/.udb/` by default: `users.json` holds user entries; `kb/` holds per-user graph data (file backend).

## Running tests

```bash
cd lib
pytest
```

## Project structure

```
lib/
├── pyproject.toml
├── src/
│   └── blue_data_user_source/
│       ├── __init__.py            # public exports
│       ├── source.py              # UserSource — main entry point (multi-user)
│       ├── types.py               # QueryResult, UDbError hierarchy
│       ├── sources/
│       │   └── file.py            # FileSource
│       ├── reasoning/
│       │   ├── metric.py          # CompletenessMetric, FreshnessMetric
│       │   └── reasoner.py        # UserQueryReasoner
│       ├── data/
│       │   ├── manager.py         # UserDataManager — KB delegation layer
│       │   └── planner.py         # UserDataPlanner
│       └── interaction/
│           ├── contact.py         # ContactManager, ContactMethod
│           └── manager.py         # InteractionManager
└── tests/
    ├── conftest.py
    └── unit/
```
