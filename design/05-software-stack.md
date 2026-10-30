# UDb — Software Stack

> This document records the stack as built for 1.0. The original plan (LlamaIndex as the LLM layer, a `blue-data-core` package with provisional `JSONSource`/`VectorSource` interfaces) is kept in the decision log as ADR-003 and ADR-004, both now superseded.

---

## Language & Runtime

| Concern | Choice |
|---------|--------|
| Language | Python |
| Supported versions | 3.12 and 3.13 (`requires-python = ">=3.12,<3.14"`), the range of the whole DI 1.0 family |
| Package manager | pip |
| Project config | `pyproject.toml` (one per package: `lib/`, `platform/cli/`, `platform/mcp/`, `platform/api/`) |

---

## LLM

| Concern | Choice |
|---------|--------|
| Client | OpenAI Python SDK (`openai.AsyncOpenAI`) |
| Default model | `gpt-4o` |

UDb's own LLM calls — query rewriting and expansion, metric assessment, contact selection, clarification questions, onboarding and answer synthesis — all go through one helper, `reasoning.reasoner._llm_complete`, which calls `AsyncOpenAI().chat.completions.create` and raises `LLMError` on any SDK failure (authentication, network, rate limit, timeout, unknown model). The model is chosen per query (`optional_properties["model"]`) or, in the CLI, by the profile setting `BLUE_DATA_USER_SOURCE_LLM_MODEL`. Extraction runs inside `blue-data-kb-source`, which makes its own OpenAI calls (its `[openai]` extra).

There is no provider abstraction: swapping providers means changing `_llm_complete` and kb-source's extraction client.

---

## Storage

All stores come from the sibling repositories and are reached through their `DataSource` classes, instantiated from a `_class` + `connection` record in the per-user `DataRegistry`. UDb never imports a concrete backend client directly.

| Store | Class (package) | Used for | Backends |
|-------|-----------------|----------|----------|
| Knowledge graph | `KBSource` (`blue-data-kb-source`) | Extracted entities, facts and property values, and one SOURCE node per added document | memory, file, Neo4j; optional keyword/semantic search index |
| JSON | `JSONSource` (`blue-data`) | Outer user registry, metadata, contact methods, session records | memory, file, Redis (RedisJSON) |
| Documents | `DocumentDataSource` (`blue-data-doc-source`) | `external_documents` (added sources) and `session_content` (clarification transcripts): parse, chunk, embed, search | memory or file vector store; OpenAI embeddings searched by vector by default (`dummy` before #172) |

`JSONSource` addresses values by dot path (`get`, `set`, `delete`). Document stores are driven by operation requests (`DOCUMENT.INGEST`, `DOCUMENT.SEARCH`, `DOCUMENT.DELETE`). The KB answers natural-language questions itself (`KBSource.answer`). See [10-data-model.md](10-data-model.md) for what each store holds.

---

## External Interfaces

### REST API

| Concern | Choice |
|---------|--------|
| Framework | FastAPI |
| ASGI server | Uvicorn |
| Settings | `pydantic-settings` (`BLUE_DATA_USER_SOURCE_*` environment variables) |

FastAPI provides automatic OpenAPI schema generation and async request handling. The routes cover databases, query, data and sources (text only in 1.0), metadata, contacts, sessions, and the callbacks that webhook and email contacts reply through. See [09-api-interface-spec.md](09-api-interface-spec.md).

### MCP Server

| Concern | Choice |
|---------|--------|
| Library | `mcp` (official MCP Python SDK, `FastMCP`) |
| Transport | stdio |

Exposes UDb operations as 23 MCP tools for consumption by LLM agents. Tool handlers delegate directly to the Python library.

### CLI

| Concern | Choice |
|---------|--------|
| Argument parsing | Click |
| Output formatting | Rich |
| Dates | Arrow |

Click handles command routing and argument parsing. Rich provides formatted terminal output (tables, progress indicators) for interactive use. Configuration comes from `blue-data` profiles (`blue-userdb profile`).

---

## External Libraries

### Sibling repositories

Installed from source, cloned beside this repository; not on PyPI.

| Package | Provides |
|---------|----------|
| `blue-data` | `DataSource`, `JSONSource` and its backends, `DataRegistry`, profiles and `ConfigResolver` |
| `blue-data-kb-source` | `KBSource` (knowledge graph, extraction, search index) |
| `blue-data-doc-source` | `DocumentDataSource` (document ingest, chunking, embedding, search) |

### Summary

| Package | Source | Role |
|---------|--------|------|
| `blue-data` | internal | Base classes, JSON storage, registry, profiles |
| `blue-data-kb-source` (`[openai,search]` extras) | internal | Knowledge graph, extraction, KB search |
| `blue-data-doc-source` | internal | Document stores |
| `rank-bm25` | PyPI | Keyword ranking for the KB search index |
| `openai` | PyPI | LLM client (via kb-source's `[openai]` extra) |
| `httpx` | PyPI | Webhook transport (library `[webhook]` extra); REST API test client |
| `aiosmtplib` | PyPI | Email transport (library `[email]` extra) |
| `fastapi`, `uvicorn`, `pydantic-settings` | PyPI | REST API |
| `mcp` | PyPI | MCP server SDK |
| `click`, `rich`, `arrow` | PyPI | CLI |
| `redis` | PyPI | Optional Redis backend (MCP `[redis]` extra) |
