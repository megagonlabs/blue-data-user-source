# Installation

## Components

`blue-data-user-source` is organized into a core library (`lib/`) and three platform components (`platform/`). Install `lib` first — every platform component depends on it, and `lib` itself depends on three sibling repositories' `lib/` packages for storage, knowledge-graph, and document primitives.

```
blue-data-user-source/
├── lib/            blue-data-user-source — the core Python library
└── platform/
    ├── cli/        blue-data-user-cli    — the `blue-userdb` command-line tool
    ├── mcp/        blue-data-user-mcp    — the MCP server (`blue-userdb-mcp`)
    └── api/        blue-data-user-api    — the REST API (`blue-userdb-api`)
```

`platform/cli`, `platform/mcp`, and `platform/api` are independent of each other — each depends only on `lib`, not on one another. Install whichever subset you need.

**Install scripts.** Each installs, editable and in dependency order, what it needs from the sibling repos (cloned beside this one) and this repo:

```bash
bash scripts/install.sh                    # everything: siblings, lib, CLI, MCP server, REST API
bash lib/scripts/install.sh                # siblings + the library (with its email/webhook/dev extras)
bash platform/cli/scripts/install.sh       # the above + the blue-userdb CLI
```

**Editable install by hand, in dependency order:**

```bash
# Sibling dependencies (local checkouts, not yet published). The KB needs its
# llm extra (LiteLLM) for every query and extraction, and search for BM25 KB search.
pip install -e ../blue-data/lib
pip install -e "../blue-data-kb-source/lib[llm,search]"
pip install -e ../blue-data-doc-source/lib

# This library
cd lib && pip install -e .

# Whichever platform components you need
cd ../platform/cli && pip install -e .
cd ../mcp && pip install -e '.[dev]'
cd ../api && pip install -e '.[dev]'
```

`platform/mcp` and `platform/api` ship an `install.sh` that runs the equivalent `pip install -e '.[dev]'`:

```bash
cd platform/mcp && bash scripts/install.sh
cd platform/api && bash scripts/install.sh
```

`platform/cli/scripts/install.sh` also installs the siblings and the library first (see above).

**Build distributable packages:**

```bash
cd lib && bash scripts/build.sh          # python -m build
cd platform/mcp && bash scripts/build.sh
cd platform/api && bash scripts/build.sh
```

`lib/scripts/publish.sh` runs `twine upload dist/*`.

---

## Requirements

- Python 3.12 or 3.13
- [`blue-data`](https://github.com/megagon-internal/blue-data), [`blue-data-kb-source`](https://github.com/megagon-internal/blue-data-kb-source), and [`blue-data-doc-source`](https://github.com/megagon-internal/blue-data-doc-source) (local sibling dependencies — not yet published to PyPI)
- An API key for any LLM feature: query rewriting/expansion, LLM-based extraction (`add_source` with `queries`), result assessment prompts, and natural-language answer synthesis. Sessions, metadata, and contact-method CRUD are plain Python with no network calls. The LLM calls go to the provider named by `BLUE_DATA_LLM_PROVIDER` (blank, the default, means `openai`; `anthropic` is the other one with a default model), through LiteLLM, with that provider's key: `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`. Document embeddings stay on OpenAI, so a new database's default `openai` embedding needs `OPENAI_API_KEY` under any provider (or use `dummy` with `bm25`).

None of the four packages are published to PyPI yet — always install from the local checkout as shown above.

---

## Optional extras

### `blue-data-user-source` (`lib/`)

| Extra | Packages | Required for |
|---|---|---|
| `webhook` | `httpx>=0.27` | The `webhook` contact method protocol |
| `email` | `aiosmtplib>=3.0` | The `email` contact method protocol (outgoing SMTP) |
| `dev` | `pytest`, `pytest-asyncio`, `pytest-recording`, `pytest-cov`, `ruff`, `pyright`, `build`, `twine` | Running the test suite, linting, type checking, and building |

```bash
pip install -e "lib[webhook,email]"
```

A `neo4j`-backed knowledge graph (`--kb-backend neo4j`) requires the `neo4j` driver on `blue-data-kb-source`, not on this package — install `blue-data-kb-source[neo4j]` alongside `lib`.

### `blue-data-user-cli` (`platform/cli/`)

No optional extras — `click`, `rich`, and `arrow` are always installed.

### `blue-data-user-mcp` (`platform/mcp/`)

| Extra | Packages | Required for |
|---|---|---|
| `redis` | `redis>=5.0` | Reserved for a Redis-backed deployment; not required for the default file-backed server |
| `dev` | `pytest`, `pytest-asyncio` | Running the test suite |

### `blue-data-user-api` (`platform/api/`)

No optional extras of its own — `fastapi`, `uvicorn[standard]`, `httpx`, and `pydantic-settings` are always installed. Enable the `email` contact method by installing `lib[email]` alongside it (`pip install -e '../../lib[email]'`).

---

## Running tests

Run from each component's root directory:

```bash
cd lib && pytest tests/unit/           # unit tests — fast, offline, no API key needed
cd lib && pytest tests/benchmarks/     # report-only LLM benchmarks; see lib/README.md for live runs
cd platform/cli && pytest              # CLI tests — all-memory backend
cd platform/mcp && pytest              # MCP server tests — in-memory UserSource
cd platform/api && pytest              # REST API tests
```

Install `lib` with the `dev` extra first:

```bash
cd lib && pip install -e ".[dev]"
```

The library's benchmark suites (`lib/tests/benchmarks/`) are separate from the default unit-test run and score query rewriting, extraction, and reasoning quality against gold-standard cases — see [guide.md](guide.md#benchmarks) and [`lib/README.md`](../lib/README.md#benchmarks) for details. They require `OPENAI_API_KEY` (cases skip cleanly without it if no VCR cassette has been recorded locally).

---

## Environment variables

Directory locations, backend selection, and server configuration are set via environment variables — there is no separate config file for the CLI, MCP server, or REST API.

| Variable | Used by | Purpose |
|---|---|---|
| `BLUE_DATA_LLM_PROVIDER` | lib, CLI, MCP, API | The provider every LLM call goes to, through LiteLLM: blank (the default) means `openai`; `anthropic` for Claude (#190) |
| `BLUE_DATA_LLM_MODEL` | lib, CLI, MCP, API | The family model, a model of that provider. Unset: the provider's default, `gpt-4o` for `openai`, `claude-opus-4-8` for `anthropic` |
| `BLUE_DATA_USER_SOURCE_LLM_MODEL`, `BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL`, `BLUE_DATA_USER_SOURCE_EXTRACTION_LLM_MODEL` | lib, CLI, MCP, API | This package's model, and per function (query reasoning and the KB's answering agent; `add_source` extraction). Each falls back to the next, then to `BLUE_DATA_LLM_MODEL`. A query's `model`, or the CLI's `--model`, wins |
| `OPENAI_API_KEY` | lib, CLI, MCP, API | The `openai` provider's key, required for its LLM calls; also for `openai` document embeddings under any provider |
| `ANTHROPIC_API_KEY` | lib, CLI, MCP, API | The `anthropic` provider's key |
| `BLUE_DATA_USER_SOURCE_HOME` | CLI | Where the CLI keeps `.profiles` and `.selected.profile` (default `~/.blue-userdb`). Environment-only — it is where profiles are read from, so it cannot come from one |
| `BLUE_DATA_USER_SOURCE_DATABASE` | CLI | Default `--database` when not passed explicitly |
| `BLUE_DATA_USER_SOURCE_SESSION` | CLI | Default `--session` when not passed explicitly |
| `BLUE_DATA_USER_SOURCE_DATA_DIR` | CLI, MCP, API | Directory for `registry.json` and per-user files (default `~/.blue-userdb`) |
| `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | CLI, MCP, API | Path to a custom `schema.json` for KB schema seeding |
| `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` | CLI, MCP, API | Path to a custom `metadata_schema.json` (default: the one packaged with the library) |
| `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` | CLI, MCP, API | Path to a custom `contact_schema.json` (default: the one packaged with the library) |
| `BLUE_DATA_USER_API_KEY` | API | API key, required on every data route (`X-API-Key` or `Authorization: Bearer`); with none set, requests get `401` |
| `BLUE_DATA_USER_API_AUTH_DISABLED` | API | `true` runs the API without a key (local development only) |
| `BLUE_DATA_USER_API_HOST` | API | Server bind address (default `127.0.0.1`) |
| `BLUE_DATA_USER_API_PORT` | API | Server port (default `8003`) |

---

## Next steps

- New to the project? Start with [quickstart.md](quickstart.md).
- Building against the library directly? See [guide.md](guide.md) and [api-reference.md](api-reference.md).
- Using the `blue-userdb` CLI, the MCP server, or the REST API day to day? See [cli.md](cli.md) / [mcp.md](mcp.md) / [api.md](api.md).
