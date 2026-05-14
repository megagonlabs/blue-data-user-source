# blue-data-user-source

Python library for UserDb — a per-user data store with natural language query and semantic retrieval.

## Requirements

- Python 3.10+
- OpenAI API key (used by the reasoning layer via `llama-index-core`)

## Installation

The package is not yet published to PyPI. Install it directly from the local source:

```bash
cd lib
pip install -e .
```

This installs the library in editable mode along with its runtime dependencies (`llama-index-core`, `llama-index-llms-openai`).

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
from blue_data_user_source.backends.memory import memory_store_factory

async def main() -> None:
    us = UserSource(properties={
        "database": "alice",
        "store_factory": memory_store_factory,
    })

    await us.create_database("alice")

    # Type 1 — register a file as a queryable source
    await us.import_source(FileSource("resume.txt"))

    # Type 2 — extract and store specific data from a file
    await us.import_source(
        FileSource("resume.txt"),
        optional_properties={"queries": ["What skills does the user have?"]},
    )

    # Natural language query
    results = await us.execute_query("jobs suitable for me")
    for r in results:
        print(r.query, "→", r.results)

asyncio.run(main())
```

Set `OPENAI_API_KEY` before running:

```bash
export OPENAI_API_KEY=sk-...
```

### Bringing your own storage

`memory_store_factory` keeps data in memory only (lost on process exit). To persist data, implement `JSONSource` and `VectorSource` from `blue_data_user_source.interfaces` and pass a matching factory:

```python
from blue_data_user_source.interfaces import JSONSource, VectorSource

class MyJsonStore(JSONSource):
    ...

class MyVectorStore(VectorSource):
    ...

def my_store_factory(name: str) -> tuple[MyJsonStore, MyVectorStore]:
    return MyJsonStore(name), MyVectorStore(name)

us = UserSource(properties={"store_factory": my_store_factory})
```

## Running tests

```bash
cd lib
pytest
```

`pythonpath` and `testpaths` are configured in `pyproject.toml`; no extra flags needed.

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
    ├── doubles/                   # in-memory source aliases (import from backends)
    └── unit/
        ├── backends/
        ├── sources/
        ├── reasoning/
        ├── data/
        └── interaction/
```
