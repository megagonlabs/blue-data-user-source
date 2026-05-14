# UserDb — Decision Log

Architectural decisions are recorded here as they are made, throughout the design process.

---

## ADR-001 — Programming Language: Python

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** Python, minimum version 3.10.

**Rationale:** Python is the dominant language in the AI/ML ecosystem, providing the broadest access to LLM clients, vector store clients, and data tooling relevant to UserDb.

**Consequences:** All library classes, interfaces, and examples are written in Python. Type hints use features available from 3.10+ (e.g. `X | Y` union syntax, `match` statements).

---

## ADR-002 — Package Manager: pip + pyproject.toml

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** Use `pip` with `pyproject.toml` for dependency management.

**Rationale:** Standard Python tooling with no additional toolchain overhead.

**Consequences:** Dependencies declared in `pyproject.toml`. No lockfile tool (e.g. Poetry, uv) required.

---

## ADR-003 — LLM Abstraction: LlamaIndex

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** Use LlamaIndex (`llama-index-core`) as the LLM abstraction layer, with OpenAI as the initial provider (`llama-index-llms-openai`).

**Rationale:** LlamaIndex provides a well-maintained provider-agnostic LLM interface, allowing the initial OpenAI integration to be swapped for other providers (Anthropic, local models, etc.) without changing application code. Provider is configured globally via `llama_index.core.Settings.llm`.

**Consequences:** All LLM calls in UserDb components (`UserQueryReasoner`, `UserDataMetric`) go through the LlamaIndex `LLM` abstraction. Adding a new provider requires only a configuration change at startup.

---

## ADR-004 — Storage Backends: blue-data-core Abstractions

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** `JSONSource` and `VectorSource` backends are provided by `blue-data-core`. UserDb interacts only with their abstract interfaces (`set`, `get`, `delete`, `query`, `keys`).

**Rationale:** Decouples UserDb from specific storage implementations (Redis, MongoDB, ChromaDB, etc.). Backend choices are delegated to `blue-data-core` and can change without affecting UserDb code.

**Consequences:** Initial interfaces are provisional and will be revised once `blue-data-core` is installed. UserDb must not import or depend on any concrete storage backend directly.

---

## ADR-005 — External Interface: REST API via FastAPI

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** Expose UserDb as an HTTP REST API using FastAPI, served by Uvicorn.

**Rationale:** FastAPI provides automatic OpenAPI schema generation, async support, and a clean decorator-based routing model with minimal boilerplate. Enables non-Python consumers and microservice deployments.

**Consequences:** REST endpoints are a thin adapter over the Python library. No business logic lives in the API layer.

---

## ADR-006 — External Interface: MCP Server

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** Expose UserDb as an MCP server using the official `mcp` Python SDK.

**Rationale:** Allows LLM agents (e.g. Claude) to call `execute_query` and `import` as native tools within an agentic context, without requiring HTTP plumbing.

**Consequences:** MCP tool handlers are thin wrappers over the Python library. MCP server can be run alongside or independently of the REST API.

---

## ADR-007 — External Interface: CLI via Click and Rich

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** Provide a command-line interface using Click for argument parsing and Rich for terminal output formatting.

**Rationale:** Click provides composable, well-tested CLI primitives. Rich enables readable formatted output (tables, progress) suited to interactive development and debugging workflows.

**Consequences:** CLI commands are thin wrappers over the Python library. No business logic lives in the CLI layer.

---

## ADR-008 — Async Throughout

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** All I/O-bound methods are `async def` across all layers — core library, reasoning, data, and interaction. Not just at interface boundaries.

**Rationale:** LlamaIndex LLM calls, storage operations, and user interactions are all I/O-bound. Making the full call stack async avoids blocking and allows the interfaces (FastAPI, MCP) to benefit from async concurrency without a sync-to-async bridge mid-stack. CLI bridges sync Click handlers to async internals via `asyncio.run()`.

**Consequences:** All public and private I/O methods use `async def`. Tests require `pytest-asyncio`. CLI commands use `asyncio.run()` at the entry point.

---

## ADR-009 — Type Checker: Pyright (Strict)

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** Use `pyright` in strict mode for static type checking.

**Rationale:** Pyright has faster incremental analysis, better inference for modern Python 3.10+ syntax, and tighter VS Code integration than mypy. Strict mode enforces complete annotations across the codebase.

**Consequences:** All packages include a `py.typed` marker. `typeCheckingMode = "strict"` set in `pyproject.toml`. Type errors are treated as CI failures.

---

## ADR-010 — Non-Unique Data Entry Keys

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** User data entry keys are not unique within a user database. Multiple entries may share the same key when populated from different sources or agents.

**Rationale:** A user's `"skills"` derived from a resume and from a session conversation are distinct provenance-bearing records that should coexist rather than overwrite each other. Uniqueness is per (key, source_id) pair, not per key alone.

**Consequences:** Retrieval by key returns a list of entries, not a single value. Callers must aggregate or select across multiple entries. The Reasoning Layer is responsible for deduplication and reconciliation when assembling query results.

---

## ADR-011 — Dual-Write Synchronization Between JSONSource and VectorSource

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** Every write to a user data entry is applied to both JSONSource and VectorSource synchronously within the same operation. JSONSource is the system of record.

**Rationale:** Synchronous dual-write ensures the two stores are always consistent from the caller's perspective. Async propagation would introduce a window where semantic search returns stale results, which is unacceptable for a query system that relies on both stores for a single response.

**Consequences:** Write latency includes the cost of both a JSON store write and a vectorization + vector store write. Write operations must handle partial failures (e.g., JSON write succeeds, vector write fails) and surface them as errors rather than silently diverging.

---

## ADR-012 — Pluggable Embedding Model for VectorSource

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** The embedding model used to vectorize data entry keys and values is a deployment-time configuration, not a compile-time choice.

**Rationale:** Embedding model selection involves tradeoffs (quality, latency, cost, self-hosted vs. hosted) that vary by deployment context. Pluggability follows the same pattern as the LLM abstraction (ADR-003) and storage backends (ADR-004).

**Consequences:** All entries within a single user database must be produced by the same model version. A model change requires re-embedding the entire database — there is no incremental migration path. The embedding model interface will be provided via LlamaIndex `Settings.embed_model`.

---

## ADR-013 — Distribution: PyPI Package + Docker Image

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** UserDb is distributed as both a PyPI package (`userdb`) and a Docker image (`userdb-server`). The PyPI package exposes the Python library with optional extras for the server and CLI. The Docker image bundles the REST API and MCP server.

**Rationale:** The two artifacts serve distinct consumers — the PyPI package for Python applications embedding UserDb directly, and the Docker image for operators running UserDb as a standalone service. Distributing both avoids forcing unnecessary dependencies on library-only consumers.

**Consequences:** The release pipeline must build and publish both artifacts on every semver tag. Version numbers must be kept in sync between the two.

---

## ADR-014 — Observability: OpenTelemetry + Prometheus + Structured JSON Logs

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** UserDb emits structured JSON logs to stdout, Prometheus-compatible metrics at `/metrics`, and OpenTelemetry traces via OTLP export. Tracing is opt-in (enabled when `OTEL_EXPORTER_OTLP_ENDPOINT` is set). Operators wire these into their own stacks.

**Rationale:** Self-hosted deployments use heterogeneous observability infrastructure (Grafana, Datadog, Jaeger, etc.). Emitting to standard interfaces (structured stdout, Prometheus, OTLP) keeps UserDb decoupled from any specific platform. Raw user data is never included in span attributes.

**Consequences:** UserDb takes a dependency on the OpenTelemetry Python SDK (`opentelemetry-sdk`, `opentelemetry-exporter-otlp`). All significant I/O boundaries (LLM calls, storage ops, interface requests) must be instrumented with spans.
