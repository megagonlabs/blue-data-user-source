# UDb — Deployment / Ops

## Overview

UDb is distributed in two forms:

- **PyPI package** (`blue-userdb`) — the Python library, for embedding UDb in other Python applications
- **Docker image** (`blue-userdb-server`) — packages the REST API and MCP server for standalone deployment

Production deployments are self-hosted. Operators provision and manage their own storage backends and observability infrastructure. UDb emits to standard interfaces and does not assume any specific platform.

> **Status in 1.0:** sections 1–8 are the target. Most of it is not built yet; §0 describes how 1.0 is actually installed, configured and run.

---

## 0. As Built in 1.0

**Packages.** Four, each with its own `pyproject.toml`, all at version `0.1.0` until the 1.0 version number is set (#116): `blue-data-user-source` (`lib/`), `blue-data-user-cli` (`blue-userdb`), `blue-data-user-mcp` (`blue-userdb-mcp`) and `blue-data-user-api` (`blue-userdb-api`). They depend on the sibling repositories `blue-data`, `blue-data-kb-source` and `blue-data-doc-source`, which are not on PyPI.

**Install.** From source: `scripts/install.sh` installs the siblings (cloned beside this repository) and all four packages, editable. Each package also has `scripts/install.sh` and `scripts/build.sh` (sdist and wheel); `lib/scripts/publish.sh` uploads the library with `twine`, but nothing has been published. There is no Docker image or compose file.

**Run.**

| Entry point | How it runs |
|-------------|-------------|
| `blue-userdb` | A process per command; state on disk |
| `blue-userdb-mcp` | stdio MCP server, launched by the agent host (Claude Desktop, Claude Code, …) |
| `blue-userdb-api` | Uvicorn on `BLUE_DATA_USER_API_HOST`:`BLUE_DATA_USER_API_PORT` (default `127.0.0.1:8003`, the user service's slot in the family port map); `platform/api/scripts/start.sh` binds `0.0.0.0` |

**Storage.** File-backed by default under `~/.blue-userdb/` (`BLUE_DATA_USER_SOURCE_DATA_DIR`): the registry, every user's JSON stores, KB and document stores. The CLI can put a user's KB in Neo4j (`database create --kb-backend neo4j`). The library also offers `RedisUserSource` (JSON stores in Redis with RedisJSON); the KB has no Redis backend.

**Configuration.**

- CLI: `blue-data` profiles (`blue-userdb profile`), which hold settings and secrets (`OPENAI_API_KEY`, `BLUE_DATA_USER_SOURCE_NEO4J_PASSWORD`, …) and export them to the command; options and environment variables override.
- REST API: `BLUE_DATA_USER_SOURCE_*` environment variables or a `.env` file — `DATA_DIR`, `ALLOWED_ORIGINS`, `SCHEMA_PATH`, `METADATA_SCHEMA_PATH`, `CONTACT_SCHEMA_PATH` — and, from the environment only, the family server settings from `blue_data.server`: `BLUE_DATA_USER_API_HOST`, `BLUE_DATA_USER_API_PORT`, `BLUE_DATA_USER_API_KEY` (required) and `BLUE_DATA_USER_API_AUTH_DISABLED` (#157).
- MCP server: `BLUE_DATA_USER_SOURCE_DATA_DIR` and the three schema paths.
- All: `OPENAI_API_KEY` for the LLM; the model defaults to `gpt-4o`.

**Observability.** Python `logging` only; no metrics endpoint, no tracing.

**CI/CD.** None yet; tests, lint and type checks run locally (see [11-testing-strategy.md](11-testing-strategy.md) §0).

---

## 1. Versioning

UDb follows [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`). Version is declared once in `pyproject.toml` and read from there by all build tooling.

- **PATCH** — bug fixes, no interface changes
- **MINOR** — backwards-compatible new features
- **MAJOR** — breaking changes to the Python library API or data model

---

## 2. PyPI Package

The `blue-userdb` package exposes the Python library (`UserSource` and related classes). It does not include the REST API, MCP server, or CLI by default. Those are available as optional extras:

```
pip install blue-userdb               # library only
pip install blue-userdb[server]       # library + REST API + MCP server
pip install blue-userdb[cli]          # library + CLI
pip install blue-userdb[all]          # everything
```

---

## 3. Docker Image

The `blue-userdb-server` image runs both the REST API (Uvicorn/FastAPI) and the MCP server as a combined process. The image is published to a container registry alongside each release.

| Port | Service |
|------|---------|
| `8000` | REST API (HTTP) |
| `8001` | MCP Server |

**Base image:** `python:3.12-slim`

**Entrypoint:** starts both services; each can be disabled via environment variable (see §5).

**Health check:** `GET /health` on port 8000.

---

## 4. Storage Backends

UDb does not bundle or manage storage backends. The operator provisions:

- A **JSON backend** (e.g., Redis, MongoDB) and provides its connection details via environment variables
- A **Vector backend** (e.g., ChromaDB) and provides its connection details via environment variables

Both backends must be available before UDb starts. UDb will fail at startup if a backend is unreachable.

### Reference docker-compose

A `docker-compose.yml` is provided in the repository root for local development and operator reference. It starts UDb alongside minimal backend instances.

```yaml
services:
  blue-userdb:
    image: blue-userdb-server:latest
    ports:
      - "8000:8000"
      - "8001:8001"
    env_file: .env
    depends_on:
      - redis
      - chromadb

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  chromadb:
    image: chromadb/chroma:latest
    ports:
      - "8002:8000"
```

---

## 5. Configuration

All configuration is via environment variables. There are no configuration files — operators use `.env` files, secrets managers, or platform-native injection.

### Core

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BLUE_DATA_USER_SOURCE_DATABASE` | No | — | Default user database ID used when none is specified per request |

### Storage

| Variable | Required | Description |
|----------|----------|-------------|
| `BLUE_DATA_USER_SOURCE_JSON_BACKEND_URL` | Yes | Connection URL for the JSON backend (e.g., `redis://localhost:6379`) |
| `BLUE_DATA_USER_SOURCE_VECTOR_BACKEND_URL` | Yes | Connection URL for the Vector backend (e.g., `http://localhost:8002`) |

### LLM and Embeddings

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes (default provider) | API key for the LLM and embedding model provider |
| `BLUE_DATA_USER_SOURCE_LLM_MODEL` | No | LLM model name (default: `gpt-4o`) |
| `BLUE_DATA_USER_SOURCE_EMBED_MODEL` | No | Embedding model name (default: `text-embedding-3-small`) |

### Server

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BLUE_DATA_USER_SOURCE_REST_PORT` | No | `8000` | Port for the REST API |
| `BLUE_DATA_USER_SOURCE_MCP_PORT` | No | `8001` | Port for the MCP server |
| `BLUE_DATA_USER_SOURCE_REST_ENABLED` | No | `true` | Set to `false` to disable the REST API |
| `BLUE_DATA_USER_SOURCE_MCP_ENABLED` | No | `true` | Set to `false` to disable the MCP server |

### Observability

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | — | OpenTelemetry collector endpoint; tracing disabled if unset |
| `OTEL_SERVICE_NAME` | No | `blue-userdb` | Service name reported in traces and metrics |

---

## 6. Observability

UDb emits structured logs, metrics, and traces. Operators wire these into their own observability stack.

### Structured Logging

All log output is JSON-formatted to stdout. Log level is controlled by the standard `LOG_LEVEL` environment variable (`DEBUG`, `INFO`, `WARNING`, `ERROR`; default: `INFO`).

Each log line includes: `timestamp`, `level`, `service`, `trace_id` (when a trace is active), and a `message` field.

### Metrics

Metrics are exposed via a Prometheus-compatible `/metrics` endpoint on the REST API port. Key metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `udb_requests_total` | Counter | Total requests by operation (`query`, `import`) and status |
| `udb_request_duration_seconds` | Histogram | End-to-end request latency |
| `udb_llm_calls_total` | Counter | LLM API calls by component and status |
| `udb_llm_duration_seconds` | Histogram | LLM call latency |
| `udb_storage_ops_total` | Counter | Storage operations by store (`json`, `vector`), op type, and status |

### Tracing

Distributed tracing uses [OpenTelemetry](https://opentelemetry.io/) with OTLP export. Tracing is enabled when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.

Trace spans are created at:

- Each external interface request
- Each Reasoning Layer operation (query rewrite, data assessment)
- Each DML operation (query plan, query execution)
- Each storage read/write
- Each LLM call

All spans include `user_id` (hashed) and `operation` as attributes. Raw user data is never included in span attributes.

---

## 7. CI/CD Pipeline

The CI/CD platform is not yet selected. Regardless of platform, the pipeline defines these stages:

| Stage | Trigger | Actions |
|-------|---------|---------|
| **Verify** | Every push / PR | Run unit tests, type check (pyright), lint |
| **Build** | Every push to `main` | Build PyPI package, build Docker image |
| **Publish** | Git tag (`v*.*.*`) | Publish to PyPI, push Docker image to registry |

The **Verify** stage must pass before any merge. The **Publish** stage is gated on a semver tag pushed by a maintainer.

---

## 8. Release Process

1. Bump version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Merge to `main`
4. Push a tag: `git tag v1.2.3 && git push origin v1.2.3`
5. CI publishes the PyPI package and Docker image automatically

No manual upload steps. All publishing is performed by CI using credentials injected as secrets.
