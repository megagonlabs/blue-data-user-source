# blue-data-user-source

A per-user personal data store that agents can query in plain language, with quality checks that ask the user when the data falls short.

Agents acting for a person need what that person knows about themselves: their background, preferences, availability and how to reach them, kept current and private. blue-data-user-source gives each user their own knowledge graph, extracted from their documents, and answers questions over it only after checking the answer is complete, fresh and privacy-safe — asking the user directly when it is not — through a Python library, the `blue-userdb` CLI, an MCP server or a REST API.

→ **[Full documentation](docs/README.md)** · **[Quick start](docs/quickstart.md)** · **[Installation](docs/installation.md)** · **[Examples](examples/README.md)** · **[CLI](docs/cli.md)** · **[MCP](docs/mcp.md)** · **[REST API](docs/api.md)**

## What it does

- **Import** documents into a user's store: every file is chunked and indexed for search, and `--query` questions extract typed entities and facts into the user's knowledge graph, each tied to the source it came from.
- **Query** the store in plain language: queries are rewritten ("my" becomes the user's name), expanded into schema-grounded sub-questions, and answered as JSON, a table, or prose.
- **Assess** every answer for completeness, freshness and privacy before returning it, with the privacy bar set by the user's own consent level.
- **Interact** with the user when an answer falls short: the system picks the best contact channel (the terminal, email, or a webhook), asks, and folds the reply back into the store.
- **Personalize** with per-user metadata (identity, preferences, availability, privacy) and contact methods that agents read when acting on the user's behalf.
- **Record** every query and clarification in sessions, so later questions have context and every answer has an audit trail.

See [docs/features.md](docs/features.md) for the full list with examples, and [examples/](examples/README.md) for runnable scripts.

## Repository layout

```
blue-data-user-source/
├── lib/                        # Python library (blue-data-user-source)
│   ├── src/blue_data_user_source/
│   ├── scripts/                # install.sh, build.sh, publish.sh
│   └── tests/
│       ├── unit/               # fast offline tests, no API key
│       └── benchmarks/         # report-only LLM benchmarks (VCR-replayed)
├── platform/
│   ├── cli/                    # Command-line interface (blue-userdb)
│   ├── mcp/                    # MCP server (blue-userdb-mcp)
│   └── api/                    # REST API (blue-userdb-api)
├── scripts/                    # install.sh — installs every package, editable
├── data/                       # resume.txt, the sample document used in the docs
├── tools/                      # convert_schema.py — regenerates schema.json from schema.txt
├── docs/                       # User-facing documentation (start at docs/README.md)
├── examples/                   # Runnable examples (start at examples/README.md)
└── design/                     # Architecture and design-process documents
```

Each platform package has its own `src/`, `tests/` and `scripts/install.sh`.

## Requirements

- Python 3.10+
- The sibling repositories [`blue-data`](https://github.com/megagon-internal/blue-data), [`blue-data-kb-source`](https://github.com/megagon-internal/blue-data-kb-source) and [`blue-data-doc-source`](https://github.com/megagon-internal/blue-data-doc-source), cloned beside this one (`../blue-data`, `../blue-data-kb-source`, `../blue-data-doc-source`); they provide the storage, knowledge-graph and document layers, and are not on PyPI
- An OpenAI API key for the LLM features: extraction, query rewriting and expansion, quality assessment, and answers in prose

```bash
export OPENAI_API_KEY=sk-...
```

## Quick start

```bash
# Install the sibling repos (from ../), the library with its extras, the CLI, the MCP server and the REST API
bash scripts/install.sh

# Create a database for Alice (add --no-onboard to skip the short onboarding interview)
blue-userdb database create alice --no-onboard
blue-userdb metadata set identity name "Alice Chen"

# Add her resume, extracting a few attributes into her knowledge graph
blue-userdb data source add data/resume.txt \
    --query "What skills does the user have?" \
    --query "What is the user's most recent job title?"

# Ask in plain language: as a table, or as a prose answer
blue-userdb data query "What skills do I have?"
blue-userdb data query "What jobs would suit me?" --format nl
```

Databases live under `~/.blue-userdb/` by default. When a check fails, `data query` asks for clarification right in the terminal. The full walkthrough — sessions, contact methods, the Python-library equivalent, and connecting an agent over MCP — is in **[docs/quickstart.md](docs/quickstart.md)**.

## Packages

| Package | Description |
|---|---|
| [lib/](lib/README.md) | `blue-data-user-source`: the core Python library (`UserSource` with memory, file and Redis backends) |
| [platform/cli/](platform/cli/README.md) | `blue-data-user-cli`: the command-line tool, installs `blue-userdb` |
| [platform/mcp/](platform/mcp/README.md) | `blue-data-user-mcp`: MCP server for LLM agents, installs `blue-userdb-mcp` |
| [platform/api/](platform/api/README.md) | `blue-data-user-api`: REST API (FastAPI), installs `blue-userdb-api` |
