# blue-data-user-source

A per-user personal data store with natural language querying, LLM-based data extraction, and interactive data quality assurance.

→ **[Full documentation](docs/README.md)** · **[Quick start](docs/quickstart.md)** · **[Installation](docs/installation.md)**

## What it does

- **Import** documents and extract structured data from them using LLM-based extraction keyed by schema-style attribute names.
- **Query** the store in natural language; results are assessed for completeness and freshness and the user is prompted for clarification when needed. Queries and their clarification interactions are grouped into sessions.
- **Interact** via configurable contact channels (the terminal, email, or a webhook) to verify stale data or fill in missing information, with responses persisted back to the store and to the session's record.
- **Output** query results as structured JSON, a Rich table, or a synthesized natural language answer.

See [docs/features.md](docs/features.md) for the full list with examples, or [examples/](examples/README.md) for runnable scripts.

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
│   ├── cli/                    # Command-line interface (blue-userdb)
│   │   ├── src/blue_data_user_cli/
│   │   └── tests/
│   ├── mcp/                    # MCP server (blue-userdb-mcp)
│   │   ├── src/blue_data_user_mcp/
│   │   └── tests/
│   └── api/                    # REST API (blue-userdb-api)
│       ├── src/blue_data_user_api/
│       └── tests/
├── docs/                       # User-facing documentation (start at docs/README.md)
└── design/                     # Architecture and design-process documents
```

## Requirements

- Python 3.10+
- OpenAI API key

```bash
export OPENAI_API_KEY=sk-...
```

## Quick start

```bash
# Install the three sibling libraries first — they are not on PyPI, so pip
# cannot resolve them for you. Clone them alongside this repo.
pip install -e ../blue-data/lib
pip install -e ../blue-data-kb-source/lib
pip install -e ../blue-data-doc-source/lib

# Install the library
cd lib && pip install -e . && cd ..

# Install the CLI
cd platform/cli && pip install -e . && cd ../..

# Create a database — this onboards interactively; add --no-onboard to skip
blue-userdb database create alice

# Register a file as a data source (Type 1 — source registration only)
blue-userdb data source add data/resume.txt

# Extract specific attributes via LLM (Type 2)
blue-userdb data source add data/resume.txt \
  --query "What skills does the user have?" \
  --query "What is the user's most recent job title?"

# Query — Rich table (default)
blue-userdb data query "What jobs are suitable for me?"

# Query — natural language answer
blue-userdb data query "What jobs are suitable for me?" --format nl
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
| [platform/cli/](platform/cli/README.md) | `blue-data-user-cli` — `blue-userdb` CLI |
| [platform/mcp/](platform/mcp/README.md) | `blue-data-user-mcp` — MCP server (`blue-userdb-mcp`) |
| [platform/api/](platform/api/README.md) | `blue-data-user-api` — REST API (`blue-userdb-api`) |
