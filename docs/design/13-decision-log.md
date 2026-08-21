# UDb — Decision Log

Architectural decisions are recorded here as they are made, throughout the design process.

---

## ADR-001 — Programming Language: Python

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** Python, minimum version 3.10.

**Rationale:** Python is the dominant language in the AI/ML ecosystem, providing the broadest access to LLM clients, vector store clients, and data tooling relevant to UDb.

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

**Consequences:** All LLM calls in UDb components (`UserQueryReasoner`, `UserDataMetric`) go through the LlamaIndex `LLM` abstraction. Adding a new provider requires only a configuration change at startup.

---

## ADR-004 — Storage Backends: blue-data-core Abstractions

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** `JSONSource` and `VectorSource` backends are provided by `blue-data-core`. UDb interacts only with their abstract interfaces (`set`, `get`, `delete`, `query`, `keys`).

**Rationale:** Decouples UDb from specific storage implementations (Redis, MongoDB, ChromaDB, etc.). Backend choices are delegated to `blue-data-core` and can change without affecting UDb code.

**Consequences:** Initial interfaces are provisional and will be revised once `blue-data-core` is installed. UDb must not import or depend on any concrete storage backend directly.

---

## ADR-005 — External Interface: REST API via FastAPI

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** Expose UDb as an HTTP REST API using FastAPI, served by Uvicorn.

**Rationale:** FastAPI provides automatic OpenAPI schema generation, async support, and a clean decorator-based routing model with minimal boilerplate. Enables non-Python consumers and microservice deployments.

**Consequences:** REST endpoints are a thin adapter over the Python library. No business logic lives in the API layer.

---

## ADR-006 — External Interface: MCP Server

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** Expose UDb as an MCP server using the official `mcp` Python SDK.

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

**Decision:** UDb is distributed as both a PyPI package (`udb`) and a Docker image (`udb-server`). The PyPI package exposes the Python library with optional extras for the server and CLI. The Docker image bundles the REST API and MCP server.

**Rationale:** The two artifacts serve distinct consumers — the PyPI package for Python applications embedding UDb directly, and the Docker image for operators running UDb as a standalone service. Distributing both avoids forcing unnecessary dependencies on library-only consumers.

**Consequences:** The release pipeline must build and publish both artifacts on every semver tag. Version numbers must be kept in sync between the two.

---

## ADR-014 — Observability: OpenTelemetry + Prometheus + Structured JSON Logs

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** UDb emits structured JSON logs to stdout, Prometheus-compatible metrics at `/metrics`, and OpenTelemetry traces via OTLP export. Tracing is opt-in (enabled when `OTEL_EXPORTER_OTLP_ENDPOINT` is set). Operators wire these into their own stacks.

**Rationale:** Self-hosted deployments use heterogeneous observability infrastructure (Grafana, Datadog, Jaeger, etc.). Emitting to standard interfaces (structured stdout, Prometheus, OTLP) keeps UDb decoupled from any specific platform. Raw user data is never included in span attributes.

**Consequences:** UDb takes a dependency on the OpenTelemetry Python SDK (`opentelemetry-sdk`, `opentelemetry-exporter-otlp`). All significant I/O boundaries (LLM calls, storage ops, interface requests) must be instrumented with spans.

---

## ADR-015 — Session Manager: Per-User, Not Global

**Date:** 2026-08-21
**Status:** Accepted

**Decision:** `SessionManager` follows the same per-user pattern as `ContactManager` and `UserDataManager` — each user's `DataRegistry` gets its own `sessions` JSONSource, rather than one global session store shared across all users.

**Rationale:** A global store was considered (sessions are conceptually "across multiple users"), but every session is always created in the context of one user, and a per-user store keeps the same convention as `contacts`/`metadata` (dotted-path CRUD on a JSONSource returned by `UserDataManager`), avoiding a second storage pattern in the codebase. Cross-user session listing, if ever needed, can iterate `UserSource._managers`.

**Consequences:** `UserDataManager` gained a fourth built-in source (`sessions`, alongside `kb`/`metadata`/`contacts`), wired into `build`/`connect`/`reset`/`destroy`. `SessionManager(database, data_manager)` is constructed the same way as `ContactManager`.

---

## ADR-016 — Per-Session DocumentDataSource for Interaction Transcripts

**Date:** 2026-08-21
**Status:** Accepted

**Decision:** Each session gets its own `DocumentDataSource` (from `blue-data-doc-source`), named `session-{session_id}` and registered in the user's `DataRegistry`, created on demand via `UserDataManager.ensure_session_doc_source()`. Resolved interaction Q/A pairs are ingested into it as text via `DocumentDataSource.ingest_text()`.

**Rationale:** Interaction transcripts are free text that benefits from the same chunk/embed/search pipeline KB sources use, and `blue-data-doc-source` already provides that pipeline. Scoping one `DocumentDataSource` per session (not one shared source per user) keeps each session's transcript independently addressable and matches the transcript's natural lifetime.

**Consequences:** `blue-data-doc-source` becomes a `blue-data-user-source` dependency (`lib/pyproject.toml`). Unlike `kb`/`metadata`/`contacts`/`sessions`, a session's `DocumentDataSource` is **not** reconstructed via `DataRegistry.connect_source()` — its embedding model is a live Python object that can't round-trip through the registry's `_class`/`connection` reflection. `UserDataManager` instead rebuilds and caches it per-process from `doc_source_props` (an `{"embedding_model": "dummy"|"openai", "vector_source": {"backend": "memory"|"file", ...}}` config passed at `create_user` time and persisted on the user's database record so reconnects see the same config). A `DummyEmbeddingModel` + in-memory vector backend is the default; CLI/MCP/REST default to a file-backed vector store instead, so transcripts survive process restarts. `blue-data-doc-source` also gained a public `DocumentDataSource.ingest_text()` method (a thin wrapper over the existing private `_pipeline.ingest_text`) so this ingestion doesn't have to go through the file-path-only `DOCUMENT.INGEST` op or reach into a private attribute.

---

## ADR-017 — Unified `interaction_id` Across Transport Correlation and Durable Records

**Date:** 2026-08-21
**Status:** Accepted

**Decision:** `ContactMethod.interact()` accepts an optional `interaction_id`. When `UserQueryReasoner.request_user_interaction` drives an interaction, it mints the id via `SessionManager.create_interaction()` first and passes it in, so the same id keys both the transport-level `pending_interactions` Future-correlation dict (webhook/email) and the durable session record. When no id is supplied (e.g. `ContactMethod` used standalone), protocols that need one generate their own, preserving prior behavior.

**Rationale:** Before this change, `interaction_id` existed only as an ephemeral, in-memory correlation key generated fresh inside `_webhook_manager`/`_email_manager` — there was no durable record of an interaction ever having happened. Introducing a second, independently-minted id for the durable record would have meant cross-referencing two ids for what is conceptually one event.

**Consequences:** `interact()`'s signature grew an optional parameter (backward compatible — existing callers and tests are unaffected). Every interaction, including `stdio` (which has no async correlation need), now gets a session-scoped id and a structured record with `status: "pending" | "resolved" | "timeout"`.

---

## ADR-018 — Reuse-or-Create Session Semantics

**Date:** 2026-08-21
**Status:** Accepted

**Decision:** `UserSource._run_query` (via `execute_query`/`execute_query_nl`/`async_execute_query`): if the caller supplies a `session` in `optional_properties`, the query is appended to that existing session (raising `QueryError` if it doesn't exist or has already ended); if omitted, a new single-query session is created automatically. `UserQueryReasoner.request_user_interaction`, called either through this path or directly, applies the same fallback if it somehow still has no session/query id.

**Rationale:** The original session-management sketch had two requirements in tension — "execute_query creates a new session" and "a session can span multiple queries." Reuse-or-create satisfies both: repeated calls without a `session` each get their own ad hoc session, while a caller that wants continuity across calls passes the `session_id` it got back.

**Consequences:** `session_id` — previously accepted by `execute_query` and silently dropped after being stored on the reasoner — is now load-bearing. `execute_query`/`execute_query_nl`/`async_execute_query` return `(results, session_id)` instead of just `results` — a breaking change to the Python library's public return shape, propagated to the CLI (`data query` auto-selects the returned session for the next call, mirroring `database create`'s auto-select), MCP (`query` tool result gains `session_id`), and REST (`POST /{name}/query` response gains `session_id`). A companion `end_session` was added (`SessionManager.end_session`, exposed via CLI `session end`, MCP `session_end`, REST `POST /{name}/sessions/{id}/end`) so a session's lifecycle has an explicit terminus, not just implicit accumulation.
