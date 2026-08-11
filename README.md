# blue-data-user-source

A per-user personal data store with natural language querying, LLM-based data extraction, and interactive data quality assurance.

## What it does

- **Import** documents and extract structured data from them using LLM-based extraction keyed by schema-style attribute names.
- **Query** the store in natural language; results are assessed for completeness and freshness and the user is prompted for clarification when needed.
- **Interact** via configurable contact channels (stdio, email, SMS, etc.) to verify stale data or fill in missing information, with responses persisted back to the store.
- **Output** query results as structured JSON, a Rich table, or a synthesized natural language answer.

## Repository layout

```
blue-data-user-source/
├── lib/                        # Python library (blue-data-user-source)
│   ├── src/blue_data_user_source/
│   └── tests/
│       ├── unit/               # fast offline tests, no API key
│       └── benchmarks/         # report-only LLM benchmarks (VCR-replayed)
│           ├── extraction/
│           ├── querying/
│           └── reasoning/
├── platform/
│   └── cli/                    # Command-line interface (udb)
│       ├── src/blue_data_user_cli/
│       └── tests/
└── docs/design/                # Architecture and design documents
```

## Requirements

- Python 3.10+
- OpenAI API key

```bash
export OPENAI_API_KEY=sk-...
```

## Quick start

```bash
# Install the library
cd lib && pip install -e . && cd ..

# Install the CLI
cd platform/cli && pip install -e . && cd ../..

# Create a database and select it as active
udb database create alice
udb database select alice

# Register a file as a data source (Type 1 — source registration only)
udb data source add resume.txt

# Extract specific attributes via LLM (Type 2)
udb data source add resume.txt \
  --query "What skills does the user have?" \
  --query "What is the user's most recent job title?"

# Query — Rich table (default)
udb data query "What jobs are suitable for me?"

# Query — natural language answer
udb data query "What jobs are suitable for me?" --format nl
```

## Testing

```bash
# Unit tests — fast, no API key
cd lib && pytest tests/unit/

# Benchmark pytest suite — cases skip without cassettes + API key
cd lib && pytest tests/benchmarks/

# Live benchmark runs (record cassettes for replay)
cd lib && python -m tests.benchmarks.extraction.run --record
cd lib && python -m tests.benchmarks.querying.run --record
cd lib && python -m tests.benchmarks.reasoning.run --record
```

See [lib/README.md](lib/README.md#running-tests) for full benchmark details.

## Packages

| Package | Description |
|---|---|
| [lib/](lib/README.md) | `blue-data-user-source` — core Python library |
| [platform/cli/](platform/cli/README.md) | `blue-data-user-cli` — `udb` CLI |
