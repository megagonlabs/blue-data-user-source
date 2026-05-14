# blue-data-user-source

Python library for UserDb — a per-user data store with natural language querying, LLM-based extraction, and interactive data quality assurance.

## Requirements

- Python 3.10+
- OpenAI API key (used by the reasoning layer via `llama-index-core`)

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

```python
import asyncio
from blue_data_user_source import UserSource, FileSource
from blue_data_user_source.backends.file import file_store_factory

async def main() -> None:
    us = UserSource(properties={
        "database": "alice",
        "store_factory": file_store_factory("~/.userdb"),
    })

    await us.create_database("alice")

    # Type 1 — register a file as a queryable source (no extraction)
    await us.import_source(FileSource("resume.txt"))

    # Type 2 — extract and store specific attributes using LLM extraction
    await us.import_source(
        FileSource("resume.txt"),
        optional_properties={"queries": ["What skills does the user have?"]},
    )
    # Stored as: {"key": "user_skills", "value": ["Python", "SQL", ...]}

    # Query — returns list[QueryResult]
    results = await us.execute_query("jobs suitable for me")
    for r in results:
        print(r.query, "→", r.results)

    # Query — returns a natural language string
    answer = await us.execute_query(
        "jobs suitable for me",
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

### `UserSource(properties)`

| Property | Type | Description |
|---|---|---|
| `database` | `str` | Default database name |
| `store_factory` | `Callable[[str], tuple[JSONSource, VectorSource]]` | Storage backend factory |

### `import_source(source, database, optional_properties)`

Imports a data source.

- **Type 1** (no `queries`): registers the source as a queryable target.
- **Type 2** (`queries` provided): runs each query through the source, uses LLM to extract relevant values, derives a schema-style attribute name (e.g. `user_skills`), and writes the result to the JSON store.

| optional_property | Type | Description |
|---|---|---|
| `queries` | `list[str]` | Queries to extract and store (Type 2) |

### `execute_query(query, database, optional_properties)`

Executes a natural language query. Contextualises and expands it via LLM, retrieves data, assesses completeness and freshness, and prompts the user for clarification when quality checks fail. Interaction responses are extracted and persisted back to the store.

Returns `list[QueryResult]` (default) or `str` when `output_form="nl"`.

| optional_property | Type | Description |
|---|---|---|
| `session` | `str` | Session ID for interaction context |
| `output_form` | `"json"` \| `"nl"` | `"json"` returns `list[QueryResult]`; `"nl"` returns a synthesized natural language string |

### `QueryResult`

```python
@dataclass
class QueryResult:
    query: str
    results: list[Any]
```

## Storage

### Built-in backends

| Factory | Description |
|---|---|
| `file_store_factory(base_dir)` | Persists each database as `{base_dir}/{name}/data.json` and `vectors.json` |
| `memory_store_factory` | In-memory only; data is lost on process exit. Useful for testing. |

### Custom backend

Implement `JSONSource` and `VectorSource` from `blue_data_user_source.interfaces`:

```python
from blue_data_user_source.interfaces import JSONSource, VectorSource

class MyJsonStore(JSONSource): ...
class MyVectorStore(VectorSource): ...

def my_store_factory(name: str) -> tuple[MyJsonStore, MyVectorStore]:
    return MyJsonStore(name), MyVectorStore(name)

us = UserSource(properties={"store_factory": my_store_factory})
```

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
│       ├── interfaces.py          # DataSource, JSONSource, VectorSource ABCs
│       ├── source.py              # UserSource — main entry point
│       ├── types.py               # QueryResult, UserDbError hierarchy
│       ├── backends/
│       │   ├── file.py            # FileJsonSource, FileVectorSource, file_store_factory
│       │   └── memory.py          # MemoryJsonSource, MemoryVectorSource, memory_store_factory
│       ├── sources/
│       │   └── file.py            # FileSource
│       ├── reasoning/
│       │   ├── metric.py          # CompletenessMetric, FreshnessMetric
│       │   └── reasoner.py        # UserQueryReasoner
│       ├── data/
│       │   ├── manager.py         # UserDataManager
│       │   ├── planner.py         # UserDataPlanner
│       │   └── registry.py        # UserDataRegistry
│       └── interaction/
│           ├── contact.py         # ContactManager, ContactMethod
│           └── manager.py         # InteractionManager
└── tests/
    ├── conftest.py
    ├── stubs/                     # llama_index stub for offline testing
    ├── doubles/                   # in-memory source aliases
    └── unit/
```
