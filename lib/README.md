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
    "store": {"backend": "file", "path": "~/.udb/db.json"},
    "schema": "data/schema.json",   # optional — used when creating/resetting databases
})

# In-memory (useful for testing)
us = UserSource({"store": {"backend": "memory"}})
```

### Manage databases

Each database (user) has its own `DataRegistry` backed by a separate JSONSource. The registry holds the KB source and any other sources added via `add_source`:

```python
async def main() -> None:
    # Create database — builds registry + KB from scratch, seeds schema
    await us.create_user(
        "alice",
        registry_props={"backend": "file", "path": "~/.udb/registries/alice.json"},
        kb_source_props={"backend": "file", "directory": "~/.udb/kb"},
        metadata_source_props={"backend": "file", "path": "~/.udb/sources/alice.metadata.json"},
        contact_source_props={"backend": "file", "path": "~/.udb/sources/alice.contacts.json"},
    )

    # Add database — connects to an existing registry that already has sources registered
    us.add_user(
        "bob",
        registry_props={"backend": "file", "path": "~/.udb/registries/bob.json"},
    )

    print(us.list_users())       # ["alice", "bob"]

    # Reset — clear KB data + imported registry entries, reseed schema
    await us.reset_user("alice")

    # Remove from main store only (KB data kept)
    us.remove_user("alice")

    # Remove from main store AND wipe all backing files
    await us.delete_user("bob")

asyncio.run(main())
```

### Add sources and query

```python
async def main() -> None:
    await us.create_user(
        "alice",
        registry_props={"backend": "file", "path": "~/.udb/registries/alice.json"},
        kb_source_props={"backend": "file", "directory": "~/.udb/kb"},
        metadata_source_props={"backend": "file", "path": "~/.udb/sources/alice.metadata.json"},
        contact_source_props={"backend": "file", "path": "~/.udb/sources/alice.contacts.json"},
    )

    # Type 1 — register a file as a queryable source (no extraction)
    await us.add_source(FileSource("resume.txt"), database="alice")

    # Type 2 — register source + extract specific knowledge via LLM
    await us.add_source(
        FileSource("resume.txt"),
        database="alice",
        optional_properties={"queries": ["What skills does the user have?"]},
    )

    # Remove a source from the registry (KG data is preserved)
    us.remove_source("alice", "resume.txt")

    # Query — returns list[QueryResult]
    results = us.execute_query("jobs suitable for me", database="alice")
    for r in results:
        print(r.query, "→", r.results)

    # Query — returns a natural language string
    answer = us.execute_query(
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
| `schema` | `str` | Default path to `schema.json` (optional); used when creating or resetting databases |

### Database management

| Method | Description |
|---|---|
| `create_user(name, registry_props, kb_source_props, metadata_source_props, contact_source_props)` *(async)* | Build registry + all three sources from scratch and seed schema |
| `add_user(name, registry_props)` | Connect to an existing registry that already has sources registered |
| `list_users()` | Return list of database names |
| `get_user(name)` | Return main-store entry for one database, or `None` |
| `remove_user(name)` | Remove database from main store; backing files unchanged |
| `reset_user(name)` *(async)* | Wipe KB data + imported registry entries, then reseed schema |
| `delete_user(name)` *(async)* | Destroy all backing files and remove from main store |

**`registry_props`** — JSONSource config for the per-database DataRegistry:

```python
{"backend": "file", "path": "~/.udb/registries/alice.json"}
{"backend": "memory"}
```

**`kb_source_props`** — KB backend config:

```python
{"backend": "memory"}
{"backend": "file", "directory": "~/.udb/kb"}
{"backend": "neo4j", "uri": "bolt://localhost:7687", "username": "neo4j", "password": "..."}
```

**`metadata_source_props`** / **`contact_source_props`** — JSONSource config for the per-database metadata and contacts stores:

```python
{"backend": "file", "path": "~/.udb/sources/alice.metadata.json"}
{"backend": "file", "path": "~/.udb/sources/alice.contacts.json"}
```

### Source management

| Method | Description |
|---|---|
| `add_source(source, database, optional_properties)` *(async)* | Register a source in the KB and optionally extract content |
| `remove_source(database, source_name)` | Remove a source from the DataRegistry (KG data preserved) |

`add_source` accepts:

| optional_property | Type | Description |
|---|---|---|
| `queries` | `list[str]` | Extraction queries — each drives one `import_text` call (Type 2) |

### Query

| Method | Description |
|---|---|
| `execute_query(query, database, optional_properties)` | Execute a natural language query; returns `list[QueryResult]` or `str` |
| `execute_query_nl(query, database, optional_properties)` | Alias — same behaviour |

`execute_query` contextualises and expands the query via LLM, retrieves data from the KB, assesses completeness and freshness, and prompts the user for clarification when quality checks fail. Interaction responses are stored back into the KB.

| optional_property | Type | Description |
|---|---|---|
| `session` | `str` | Session ID for interaction context |
| `output_form` | `"json"` \| `"nl"` | `"json"` returns `list[QueryResult]`; `"nl"` returns a synthesized natural language string |
| `top_k` | `int` | Max KB results per sub-query (default: 10) |

### Data access

| Method | Description |
|---|---|
| `list_data(database)` *(async)* | Raw data entries from the KB (`list[dict]`) |
| `describe_data(database)` *(async)* | Natural language summary of KB data (`str`) |
| `list_sources(database, source_id=None)` *(async)* | KB SOURCE nodes (`list[dict]`), optionally filtered by ID |
| `describe_sources(database, source_id=None)` *(async)* | Natural language summary of sources (`str`) |
| `list_metadata(database)` | User metadata dict from the metadata source |
| `get_metadata(database, key)` | Single metadata value |
| `set_metadata(database, key, value)` | Set a metadata value |
| `delete_metadata(database, key)` | Delete a metadata value |

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

Persists data to JSON files in a directory — one file per database.

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

The `udb` CLI exposes all library operations. See [platform/cli/README.md](../platform/cli/README.md) for full details.

```
udb [--database NAME] [--data-dir DIR] [--schema-path PATH] COMMAND

database commands:
  udb database create NAME    Create a new database
  udb database delete NAME    Delete a database and all its data
  udb database select NAME    Set the active database
  udb database list           List all databases
  udb database search KEYWORD Search databases by name
  udb database reset          Clear KB data and reseed schema
  udb database config show    Show stored configuration

data commands:
  udb data query TEXT         Execute a natural language query
  udb data search QUERY       Search entities and facts
  udb data list               List all entities and facts
  udb data import FILE        Import instance data (from udb data export)
  udb data export             Export instance data as JSON
  udb data extract TEXT       Extract entities/facts from free text via LLM
  udb data source list        List data sources
  udb data source add FILE    Register a file source (optionally extract)
  udb data source remove NAME Remove a source from the registry

schema commands:
  udb schema list             List classes and relations
  udb schema import FILE      Import a schema
  udb schema export           Export schema as JSON
  udb schema search QUERY     Search schema elements
```

Database files are stored under `~/.udb/` by default.

## Running tests

### Unit tests

Fast, fully offline, no API key required. Covers `UserDataManager`, `UserQueryReasoner`, `ContactManager`, `FreshnessMetric`, `CompletenessMetric`, and `UserDataPlanner`.

```bash
cd lib
pytest tests/unit/
```

85 tests, ~1 s.

### Benchmarks

Report-only: benchmarks never fail on a metric regression — they print and write scores so drift is visible over time. They are split into three modules:

| Module | Cases | What it measures |
|---|---|---|
| `extraction` | 4 | User-profile text stored via `store_data`, then queried; scores answer coverage |
| `querying` | 5 | Same KB data queried using second-person, "the user", and by-name phrasing; scores result alignment |
| `reasoning` | 16 | Query contextualization precision, expansion coverage, completeness metric, freshness metric, and interaction question appropriateness per contact channel |

LLM-backed benchmarks (extraction, querying, and all reasoning cases except freshness) use [VCR cassettes](https://vcrpy.readthedocs.io/en/latest/) for replay. They skip automatically when no cassette exists and `OPENAI_API_KEY` is unset:

```bash
# Run all benchmarks — LLM cases skip, freshness cases run
cd lib
pytest tests/benchmarks/

# Run a specific module
pytest tests/benchmarks/extraction/
pytest tests/benchmarks/querying/
pytest tests/benchmarks/reasoning/
```

**Freshness metric** cases (`reasoning/cases/freshness_*.yaml`) are deterministic — they run without a cassette or API key and report the numeric score for data aged 1 day, 90 days, 400 days, two mixed nodes, and zero nodes.

#### Live runs and cassette recording

Each benchmark module ships a `run.py` that runs live against the real OpenAI API, prints a progress line per case, and optionally writes VCR cassettes for later pytest replay:

```bash
export OPENAI_API_KEY=sk-...

# Run all extraction cases with the default model (gpt-4o)
python -m tests.benchmarks.extraction.run

# Run a specific case or model
python -m tests.benchmarks.extraction.run --case basic_profile --model gpt-4o-mini

# Run and record cassettes for pytest replay
python -m tests.benchmarks.extraction.run --record

# Querying benchmark — shows addressing style in progress line
python -m tests.benchmarks.querying.run
python -m tests.benchmarks.querying.run --record

# Reasoning benchmark — freshness cases are deterministic (no API key needed)
python -m tests.benchmarks.reasoning.run --type freshness   # no API key required
python -m tests.benchmarks.reasoning.run                    # all types
python -m tests.benchmarks.reasoning.run --type contextualization --type expansion
python -m tests.benchmarks.reasoning.run --record
```

Common options (all three runners):

| Option | Description |
|---|---|
| `--model MODEL` | Model to use (repeatable; default: `gpt-4o`) |
| `--case CASE_ID` | Run only this case (repeatable; default: all) |
| `--judge-model MODEL` | Model for LLM-judge scoring (default: `gpt-4o-mini`) |
| `--out PATH` | JSON score report path (default: `.reports/live-<timestamp>.json`) |
| `--detail-out PATH` | JSONL detail log path |
| `--record` | Write cassettes to `cassettes/` for pytest replay |

The reasoning runner also accepts `--type` to filter by benchmark type (`contextualization`, `expansion`, `completeness`, `freshness`, `appropriateness`).

Cassettes are saved to `tests/benchmarks/<module>/cassettes/`. Commit them alongside the case files so CI can replay without network access.

#### Benchmark reports

After each run a JSON report and a JSONL detail log are written to `tests/benchmarks/<module>/.reports/` (git-ignored). A Rich table is also printed to the terminal.

## Project structure

```
lib/
├── pyproject.toml
├── src/
│   └── blue_data_user_source/
│       ├── __init__.py
│       ├── source.py              # UserSource — multi-database entry point
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
    ├── conftest.py                # shared manager fixture (all-memory backends)
    ├── unit/
    │   ├── doubles/
    │   │   └── sources.py         # make_mock_kb helper
    │   ├── data/                  # test_query_executor, test_query_planner, test_source_manager
    │   ├── interaction/           # test_contact_manager, test_interaction_manager
    │   ├── reasoning/             # test_data_assessor, test_query_rewriter
    │   └── sources/               # test_file_source
    └── benchmarks/
        ├── common/                # cases, runner, reasoning_runner, scoring, reporting, capture
        ├── extraction/
        │   ├── cases/*.yaml       # user-profile extraction cases
        │   └── cassettes/         # VCR recordings (committed)
        ├── querying/
        │   ├── cases/*.yaml       # NL query cases (second-person, "the user", by-name)
        │   └── cassettes/
        └── reasoning/
            ├── cases/*.yaml       # contextualization, expansion, completeness,
            │                      # freshness (deterministic), appropriateness
            └── cassettes/
```
