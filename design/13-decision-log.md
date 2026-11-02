# UDb — Decision Log

Architectural decisions are recorded here as they are made, throughout the design process.

---

## ADR-001 — Programming Language: Python

**Date:** 2026-05-12
**Status:** Accepted

**Decision:** Python, minimum version 3.12; 1.0 supports 3.12 and 3.13 (`requires-python = ">=3.12,<3.14"`), the range of the whole DI 1.0 family: blue-data 1.0 caps below 3.14 and Genie does not import on 3.11 (#187).

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
**Status:** Superseded in 1.0 — LLM calls use the OpenAI SDK directly (`openai.AsyncOpenAI`, one helper, `_llm_complete`); LlamaIndex is not a dependency. See [05-software-stack.md](05-software-stack.md).

**Decision:** Use LlamaIndex (`llama-index-core`) as the LLM abstraction layer, with OpenAI as the initial provider (`llama-index-llms-openai`).

**Rationale:** LlamaIndex provides a well-maintained provider-agnostic LLM interface, allowing the initial OpenAI integration to be swapped for other providers (Anthropic, local models, etc.) without changing application code. Provider is configured globally via `llama_index.core.Settings.llm`.

**Consequences:** All LLM calls in UDb components (`UserQueryReasoner`, `UserDataMetric`) go through the LlamaIndex `LLM` abstraction. Adding a new provider requires only a configuration change at startup.

---

## ADR-004 — Storage Backends: blue-data-core Abstractions

**Date:** 2026-05-12
**Status:** Superseded in 1.0 — the abstractions come from `blue-data` (`DataSource`, `JSONSource`, `DataRegistry`), `blue-data-kb-source` (`KBSource`) and `blue-data-doc-source` (`DocumentDataSource`); there is no `VectorSource` store. The principle stands: UDb never imports a concrete backend.

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
**Status:** Not implemented in 1.0 — there are no key-value data entries; user data is KB facts and document chunks, each tied to its source. See [10-data-model.md](10-data-model.md) §0.

**Decision:** User data entry keys are not unique within a user database. Multiple entries may share the same key when populated from different sources or agents.

**Rationale:** A user's `"skills"` derived from a resume and from a session conversation are distinct provenance-bearing records that should coexist rather than overwrite each other. Uniqueness is per (key, source_id) pair, not per key alone.

**Consequences:** Retrieval by key returns a list of entries, not a single value. Callers must aggregate or select across multiple entries. The Reasoning Layer is responsible for deduplication and reconciliation when assembling query results.

---

## ADR-011 — Dual-Write Synchronization Between JSONSource and VectorSource

**Date:** 2026-05-12
**Status:** Not implemented in 1.0 — there is no JSON/Vector pair to keep in sync (see ADR-010).

**Decision:** Every write to a user data entry is applied to both JSONSource and VectorSource synchronously within the same operation. JSONSource is the system of record.

**Rationale:** Synchronous dual-write ensures the two stores are always consistent from the caller's perspective. Async propagation would introduce a window where semantic search returns stale results, which is unacceptable for a query system that relies on both stores for a single response.

**Consequences:** Write latency includes the cost of both a JSON store write and a vectorization + vector store write. Write operations must handle partial failures (e.g., JSON write succeeds, vector write fails) and surface them as errors rather than silently diverging.

---

## ADR-012 — Pluggable Embedding Model for VectorSource

**Date:** 2026-05-12
**Status:** Superseded in 1.0 — embeddings are configured per store: the document stores take `embedding_model` (`openai` by default since #172, or `dummy`) and a `search_mode` (#173), and the KB search index takes an OpenAI embedding model.

**Decision:** The embedding model used to vectorize data entry keys and values is a deployment-time configuration, not a compile-time choice.

**Rationale:** Embedding model selection involves tradeoffs (quality, latency, cost, self-hosted vs. hosted) that vary by deployment context. Pluggability follows the same pattern as the LLM abstraction (ADR-003) and storage backends (ADR-004).

**Consequences:** All entries within a single user database must be produced by the same model version. A model change requires re-embedding the entire database — there is no incremental migration path. The embedding model interface will be provided via LlamaIndex `Settings.embed_model`.

---

## ADR-013 — Distribution: PyPI Package + Docker Image

**Date:** 2026-05-12
**Status:** Not implemented in 1.0 — the four packages (`blue-data-user-source`, `-cli`, `-mcp`, `-api`) are installed from source with `scripts/install.sh`; nothing is published to PyPI and there is no Docker image. See [12-deployment-ops.md](12-deployment-ops.md).

**Decision:** UDb is distributed as both a PyPI package (`blue-userdb`) and a Docker image (`udb-server`). The PyPI package exposes the Python library with optional extras for the server and CLI. The Docker image bundles the REST API and MCP server.

**Rationale:** The two artifacts serve distinct consumers — the PyPI package for Python applications embedding UDb directly, and the Docker image for operators running UDb as a standalone service. Distributing both avoids forcing unnecessary dependencies on library-only consumers.

**Consequences:** The release pipeline must build and publish both artifacts on every semver tag. Version numbers must be kept in sync between the two.

---

## ADR-014 — Observability: OpenTelemetry + Prometheus + Structured JSON Logs

**Date:** 2026-05-12
**Status:** Not implemented in 1.0 — the packages log through Python `logging` only; there are no metrics or traces.

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
**Status:** Accepted; amended — 1.0 keeps one shared `session_content` source per user rather than one per session; the reconnect and configuration consequences below still hold.

**Decision:** Each session gets its own `DocumentDataSource` (from `blue-data-doc-source`), named `session-{session_id}` and registered in the user's `DataRegistry`, created on demand via `UserDataManager.ensure_session_doc_source()`. Resolved interaction Q/A pairs are ingested into it as text via `DocumentDataSource.ingest_text()`.

**Rationale:** Interaction transcripts are free text that benefits from the same chunk/embed/search pipeline KB sources use, and `blue-data-doc-source` already provides that pipeline. Scoping one `DocumentDataSource` per session (not one shared source per user) keeps each session's transcript independently addressable and matches the transcript's natural lifetime.

**Consequences:** `blue-data-doc-source` becomes a `blue-data-user-source` dependency (`lib/pyproject.toml`). Unlike `kb`/`metadata`/`contacts`/`sessions`, a session's `DocumentDataSource` is **not** reconstructed via `DataRegistry.connect_source()` — its embedding model is a live Python object that can't round-trip through the registry's `_class`/`connection` reflection. `UserDataManager` instead rebuilds and caches it per-process from `doc_source_props` (an `{"embedding_model": "dummy"|"openai", "vector_source": {"backend": "memory"|"file", ...}}` config passed at `create_user` time and persisted on the user's database record so reconnects see the same config). A `DummyEmbeddingModel` + in-memory vector backend is the default; CLI/MCP/REST default to a file-backed vector store instead, so transcripts survive process restarts. *(1.0: new users embed with OpenAI and search by vector, #172; the search mode is recorded with the user, #173.)* `blue-data-doc-source` also gained a public `DocumentDataSource.ingest_text()` method (a thin wrapper over the existing private `_pipeline.ingest_text`) so this ingestion doesn't have to go through the file-path-only `DOCUMENT.INGEST` op or reach into a private attribute.

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

---

## ADR-019 — `UserDataManager.execute_query` Also Searches session_content and external_documents

**Date:** 2026-09-03
**Status:** Accepted

**Decision:** `UserDataManager.execute_query` (the per-sub-question retrieval step the Reasoning Layer calls once per expanded question — see §2/§4 of [04-detailed-architecture.md](04-detailed-architecture.md)) now retrieves from all three of the manager's queryable sources, not just `kb`: it calls `KBSource.answer()` as before, then runs `DOCUMENT.SEARCH` against `session_content` and `external_documents` (top `DOC_SEARCH_TOP_K = 5` chunks each) via `ensure_session_doc_source()`/`ensure_external_documents_source()`, and merges all three into one `(data, metadata)` result. Each merged chunk is tagged `"source": "session_content" | "external_documents"` in `data`, and `metadata[chunk_id] = {"source": ..., "extraction": ...}`, matching the shape `CompletenessMetric`/`FreshnessMetric` already expect from KB provenance entries.

**Rationale:** `session_content` and `external_documents` were being ingested into (transcripts, added files) but never queried — the DML's "aggregate evidence across heterogeneous data sources" responsibility (§4) wasn't implemented for them. `KBSource.answer()` has no hook to inject extra context into its own agent loop (verified: no parameter anywhere in the `blue-data-kb-source` answer chain accepts additional documents), so the two document sources are queried independently, in parallel with the KB call already happening once per sub-question, rather than folded into the KB agent's reasoning.

**Consequences:** Fixed a latent bug found while wiring this up: `ensure_session_doc_source` never called `DOCUMENT.ENSURE_INDEX` (unlike `ensure_external_documents_source`, which always has), so `session_content`'s vector index was never created and `DOCUMENT.SEARCH` against it silently returned nothing even after transcripts were ingested — it now calls `ENSURE_INDEX` at construction, matching `external_documents`. `execute_query` gained an optional `session_id: str | None = None` parameter (threaded through from `UserSource._run_query`, which already tracks it) so it can pass a real id to `ensure_session_doc_source`; the parameter is currently vestigial there (session_content is one shared source across all sessions — see ADR-016's now-superseded per-session framing, still reflected in the class docstring) but keeps the call honest rather than passing a placeholder. This is a different integration point than §2's "Context Expansion Sources" (Query Rewriter-time contextualization) still describes — that use of `session_content` remains unimplemented; this ADR covers per-sub-question retrieval only.

---

## ADR-020 — Query Rewrite Substitutes the User's Name for Self-References

**Date:** 2026-09-03
**Status:** Accepted

**Decision:** `UserQueryReasoner.contextualize_query` now instructs the LLM to replace every self-reference to the user — `"you"`/`"your"`, `"the user"`, third-person pronouns, or the user's own name — with the user's actual name (`identity.name`, falling back to the database id), including the possessive form, while leaving references to other people untouched.

**Rationale:** A rewritten query like `"What is the user's age?"` is ambiguous once it reaches sub-question generation and metric evaluation — nothing distinguishes "the user" from a third party the query might also mention. Substituting the concrete name removes that ambiguity at the earliest point in the pipeline, so every downstream stage (`expand_query`, metrics, interaction prompts) already operates on an unambiguous reference.

**Consequences:** `contextualize_query` depends on `identity.name` being set for best results; it still falls back to the database id when absent. Prompts throughout the reasoning pipeline that previously said "the user" now consistently use the resolved name.

---

## ADR-021 — Query Expansion Grounded in KB Schema Facets, Zero-or-More Sub-Questions

**Date:** 2026-09-03
**Status:** Accepted

**Decision:** `UserQueryReasoner.expand_query` now exports the KB schema (`KBSource.export_database_schema`) and summarizes it into a compact list of queryable facets (entity attributes and non-structural relations) to ground sub-question generation. Each sub-question must be a well-formed, third-person factual lookup — never a clarification question addressed to the user — and must target a distinct facet. The LLM may return an empty list when the query is already a single specific lookup; results are capped at 5.

**Rationale:** Without grounding, the LLM would invent sub-questions the data store has no way to answer, and the prior "always return at least the original query" fallback padded simple queries with filler sub-questions that added LLM cost without adding coverage.

**Consequences:** `expand_query` now needs a `manager` (to reach `KBSource.export_database_schema`) to get schema grounding; without one it falls back to ungrounded expansion. Callers must handle an empty list from `expand_query` — `UserSource._run_query` already does, appending the rewritten query itself to the (possibly empty) expansion list rather than relying on `expand_query` to include it.

---

## ADR-022 — `resolve_via_interaction` Owns the Assess-Interact-Reassess Loop

**Date:** 2026-09-04
**Status:** Accepted

**Decision:** `UserQueryReasoner.resolve_via_interaction(query, assessment_query, data, metadata, max_rounds=3, topic=None)` consolidates what was previously three separate calls inlined in `UserSource._run_query` (`assess_query_results` → `assess_user_interaction` → `request_user_interaction`, run once) into a single method that loops: assess, and while any metric fails, interact and reassess, up to `max_rounds` times, stopping as soon as every metric passes.

**Rationale:** The single-shot version could only ever ask the user once per query, even if their answer still left metrics failing. Owning the full loop in the reasoner (rather than in `UserSource`) also keeps `_run_query` a thin orchestrator and makes the loop unit-testable independent of the query pipeline.

**Consequences:** `UserSource._run_query` gained the `max_interaction_rounds` optional property (default 3) and now surfaces only the newly-collected user responses (one per round) as a single `QueryResult`, rather than the previous single-round augmented-data slice. `resolve_via_interaction` accepts an optional `topic`, threaded through to `request_user_interaction` → `ContactManager.identify_contact_method` — see ADR-023's `availability.by_topic` addition.

---

## ADR-023 — Metadata Schema Trimmed to Identity/Preferences/Availability/Privacy; Availability Gains Out-of-Office and Per-Topic Overrides

**Date:** 2026-09-04
**Status:** Accepted

**Decision:** `data/metadata_schema.json` drops the `policy`, `credentials`, `skills`, and `instructions` categories (and `identity.role`, `preferences.output_format`, `availability.response_sla`), none of which were read anywhere in the codebase. `availability` gains `out_of_office` (bool) and `by_topic` (dict of per-topic overrides for `working_hours`/`preferred_channel`/`out_of_office`). `ContactManager._choose_contact_method` now uses `identity.timezone` to localize `availability.working_hours` and compute whether the current time falls within it, and prefers an asynchronous contact method (`email`, `webhook`, `notification` — `ContactMethod.is_async`) when `out_of_office` is true or the current time is outside working hours.

**Rationale:** An unused, speculative schema (agent permissions, credential storage, skills, standing instructions) added surface area — seeded keys, CLI/MCP examples, tests — with no corresponding logic reading them, while `identity.timezone` and `identity.pronouns` (already present) were unused by the reasoning/interaction code that could most benefit from them. Trimming to only what's read, and wiring `timezone`/`pronouns`/the new availability fields into the contact-selection and interaction-phrasing logic that already existed, keeps the schema honest about what the system actually does.

**Consequences:** Existing user databases seeded from the old schema retain the removed keys until reset; `UserDataManager` does not migrate them. CLI (`blue-userdb metadata get/set/delete`) and MCP (`set_metadata`) docstrings/examples were updated to reference the new keys. `request_user_interaction`'s clarification-question prompt now includes `identity.pronouns` when set, for correct third-person phrasing. `synthesize_results_nl`/`synthesize_expanded_nl` now append a locale-formatting instruction (dates/numbers/currency) when `identity.locale` is set (`UserQueryReasoner._locale_instruction`).

---

## ADR — CLI: Profile-Driven Configuration (`blue-userdb profile`)

**Date:** 2026-09-16
**Status:** Accepted

**Decision:** The `blue-userdb` CLI gains a `profile` command group — `add`, `remove`, `list`, `config`, `inspect`, `select` — and every configuration value now comes from the selected profile. A profile is a named section of `~/.blue-userdb/.profiles` (INI, `0600`), selected via `~/.blue-userdb/.selected.profile`; the first `blue-userdb` command creates and selects `default`, so a fresh install needs no setup step. Parameters are declared in `profile_spec.json` — `default`, `prompt`, `required`, optional `inherits`, and a `cast` — merged with the family-wide `base_spec()`. Resolution order is **command option > environment variable > profile > spec default**. The engine is `blue_data.utils.config` in the `blue-data` repo, shared with `blue-data-kb-source`; this repo adds only a spec and a Click layer that is a deliberate near-copy of `blue_data_kb_cli.profile`.

**Rationale:** Implements the Profiles & configuration, Secrets and Local storage sections of the CLI compliance checklist. The checklist requires `profile` to behave identically across the family, which is why the engine is shared and the command layer is a near-copy rather than a fresh design: a divergence here would be a defect, not a variation. Three choices are specific to this CLI. `UserQueryReasoner` now takes a `model` and threads it to all 11 `_llm_complete` call sites, with `UserSource.onboard_user`/`describe_data`/`describe_sources` accepting one and the query path carrying it in `optional_properties` alongside `session`/`output_form`; the alternative — having `_llm_complete` read the environment directly — would have worked with the profile immediately but left the library's own callers unable to choose a model. `blue-userdb database create`'s eight backend defaults *are* profile parameters, unlike the KB CLI where equivalent settings stayed with `database config`: `blue-userdb` has no `database config set`, so the profile is the only place a per-environment default can live. `BLUE_DATA_USER_SOURCE_DATABASE` stays required with no default, preserving today's "No database selected" error rather than silently inventing one.

**Consequences:** `blue-userdb data query` gained a `--model` it never had — the reasoner's model was unreachable from the CLI before. `--log-limit` and the `database create` backend options now default to `None` so "not given" is distinguishable from an explicit choice. `BLUE_DATA_USER_SOURCE_HOME` is a new environment-only variable naming the directory profiles are read from; it defaults to the same `~/.blue-userdb` the data lives in, so everything sits together unless a profile points the data elsewhere. Test isolation had to be rebuilt: the suite isolated `--data-dir` only, and profiles are read before options are applied, so the first run of the new code wrote a `.profiles` into the developer's real `~/.blue-userdb` — the fixture now isolates the home, clears every spec parameter, snapshots the environment per invocation, and fails loudly if anything escapes. `--neo4j-password` remains a command-line option, matching the KB CLI's deferral of the same item.

---

## ADR-024 — Schema Paths Are Configuration; Servers Share the Names, Not the Values

**Date:** 2026-09-16
**Status:** Accepted

**Decision:** `metadata_schema` and `contact_schema` join `schema` as configurable paths. The CLI declares `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` and `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` in `profile_spec.json` as optional `file` parameters, with matching `--metadata-schema-path`/`--contact-schema-path` options. The MCP and API servers read the same two variable names directly from the environment — MCP via `os.environ`, API via `pydantic-settings`' `env_prefix` — and share nothing else: neither imports `blue_data_user_cli`, neither reads `~/.blue-userdb/.profiles` or `.selected.profile`. An unset variable is omitted from the source properties so the library's packaged defaults apply.

**Rationale:** The library already accepted both as source properties (`UserSource.__init__`, defaulting to `data/metadata_schema.json` and `data/contact_schema.json`), but nothing could set them: the CLI's profile spec covered only `schema`, and `blue-userdb metadata list`/`blue-userdb contact list` read module-level constants loaded at import from the packaged copies, which no configuration could reach. Sharing variable *names* across CLI, MCP and API means one thing to learn and one thing to document; sharing *values* would mean a developer's CLI profile silently reconfiguring a running server, which is a debugging trap and a deployment hazard — the servers are meant to be independently buildable and deployable (`blue_data_user_mcp.config`'s docstring states this as a rule).

**Consequences:** `blue-userdb`'s three seeding commands (`database create`/`onboard`/`reset`) pass all three paths via a new `_seeding_source(obj)`; the other 32 `_make_source` call sites leave them unset, since `UserSource.__init__` only overwrites a registered source property when one is explicitly provided. The display path now goes through a cached `_schema_doc()` that falls back to the packaged copy with a warning rather than an empty schema when a configured file is unreadable — a broken path degrades the CLI's schema hints instead of emptying them. `_METADATA_SCHEMA_PATH`, an unreferenced constant pointing six `parent`s up at a repo-relative path that could not resolve from an installed package, was removed. `platform/api` gained its first tests; both server packages now assert in `test_config.py` that they import nothing from the CLI and that a `.profiles` file on disk cannot reach them.

---

## ADR-025 — Connection Protocol: `user` Names the Family; the Backend Segment Names the Registry

**Date:** 2026-09-16
**Status:** Accepted

**Decision:** `UserSource` reports the connection protocol `user`, not `user/registry`. Concrete subclasses keep the family-wide `<family>/<backend>` shape and name their **outer registry's** backend: `user/file`, `user/memory`, `user/redis`.

**Rationale:** Elsewhere in `blue-data` the second segment names where the bytes live for the whole source — `sql/postgres`, `json/redis`, `vector/chromadb`. A `UserSource` is a composite and cannot honor that literally: the per-user `kb`/`metadata`/`contacts`/`sessions`/`documents` backends are chosen at `create_user` time and may differ between users of the same source. The one backend fixed at instantiation is the registry holding the catalog of which users exist, which is exactly what separates `FileUserSource` from `MemoryUserSource` from `RedisUserSource` — so that is what the segment names, and `docs/architecture.md` already described it that way. `user/registry` broke the convention it appeared to follow: "registry" is not a backend but this family's own machinery, so a consumer splitting on `/` got a backend name that names no backend. Naming the family alone is true — family known, backend unspecified — and does not force a breaking change on anyone subclassing `UserSource` without their own registry. The protocol string carries no instantiation burden here in any case: `DataRegistry.create_source` dispatches on `_class`, and the sole protocol dispatch in the codebase (`get_data_source_schema`'s `protocol == "bn"`) is a family-level check.

**Consequences:** A bare `UserSource` reports `user`; all three concrete subclasses already override, so no shipped backend changes its string. Per-user backend discovery stays where it belongs — each leaf source record carries its own honest protocol (`kb/file`, `json/file`, `vector/file`) — rather than being encoded in the composite's. `docs/architecture.md` gained the two-level reading of the convention, and the lifecycle test now asserts the family-only default.

---

## ADR-026 — The Neo4j Password Is a Profile Secret, Never a Command-Line Option

**Date:** 2026-10-11
**Status:** Accepted (supersedes the `--neo4j-password` note in "CLI: Profile-Driven Configuration")

**Decision:** `blue-userdb database create` no longer has a `--neo4j-password` option. The password is the profile parameter `BLUE_DATA_USER_SOURCE_NEO4J_PASSWORD`, cast `secret`: `blue-userdb profile config` prompts for it and stores it encoded or as a `$VAR` reference, `profile inspect` masks it, and an exported variable of the same name overrides it.

**Rationale:** A value given as a command-line option lands in shell history and in process listings, which the CLI compliance checklist (#104, Secrets) rules out. The profile machinery already handles secrets this way for API keys. The option had been kept for compatibility, matching the KB CLI's deferral; with no release yet depending on it, 1.0 is the cheapest moment to remove it.

**Consequences:** Scripts that passed `--neo4j-password` must set the profile parameter or export the variable instead; `database create --kb-backend neo4j` without one fails with a message naming both. The KB CLI still has the option, so the family differs here until it follows.


---

## ADR-027 — UserSource Meets blue-data's DataSource Contract; the Session Id Moves to `async_execute_query`

**Date:** 2026-10-21
**Status:** Accepted (amends ADR-018's return shape for the `DataSource` methods)

**Decision:** `UserSource` passes blue-data's conformance kit (`blue_data.testing.conformance.DataSourceConformance`, design/14 in blue-data), run in `lib/tests/unit/sources/test_conformance.py` for the memory and file backends (#164). As a result:

- **Rows (§1).** `execute_query` and `execute_query_nl` return `list[dict]` rows: the answer's table for `"json"`, one `{"answer": ...}` row for `"nl"`, and one `{"result", "expanded"}` row with `include_expanded`. They no longer return `(answer, session_id)` (#167).
- **The session id.** It travels through `async_execute_query`, which still returns `(answer, session_id)` and is not part of the `DataSource` interface. The CLI, MCP server and REST API all use it. A caller of the `DataSource` forms that needs a session creates it first and passes it as `session`.
- **No `asyncio.run` in sync methods (§6).** The synchronous `DataSource` methods run their async work through one bridge (`_sync.run_sync`). The bridge uses `asyncio.run` when no loop is running, and a worker thread with its own loop when one is (#168).
- **NL-tool signature (§5).** `execute_nl_tool` accepts `read_only`; every tool here only reads. `fetch_entity_stats` accepts the contract's `row_sample_size` (#169).
- **`llm_fn` is unused.** `execute_query_nl` accepts `llm_fn` and `schema` but does not use them. This is an allowed exception: answering runs this source's own pipeline (rewriting, expansion, quality assessment, clarification), which a `prompt -> text` function cannot drive. blue-data-kb-source documents the same exception.

**Rationale:** Under ADR-018, the session id rode along as a second tuple element. That broke every generic `DataSource` caller: the registry, the planner, and frameworks that expect rows. The contract names exactly that pattern as forbidden. Keeping the richer tuple on the async method preserves what this repo's own front ends need, without bending the shared interface.

**Consequences:**
- Library callers that unpacked `answer, session_id = us.execute_query(...)` switch to `await us.async_execute_query(...)`, or to the rows.
- The CLI's `data query` now calls `async_execute_query`.
- Inside a running loop, the bridge runs the coroutine on another thread with its own fresh loop. Each synchronous call already got a fresh loop from `asyncio.run`, so loop-bound state behaves as before; only the thread differs.


---

## ADR-028 — LLM Calls Go Through LiteLLM to the Family Provider

**Date:** 2026-10-31
**Status:** Accepted (supersedes #175's rule that the family model applies only under `openai`)

**Decision:** Every LLM call of user-source goes through LiteLLM to the provider named by `BLUE_DATA_LLM_PROVIDER`, blank meaning `openai`, passed as LiteLLM's `custom_llm_provider` (#190). `blue_data_user_source.llm` holds the client (`AsyncClient`, OpenAI's call shape), the provider's default model (`gpt-4o` / `claude-opus-4-8`), and the key check (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`) made before the first call. A model resolves the same way in the library, the CLI, the MCP server and the REST API: the call's `model`, the function's `BLUE_DATA_USER_SOURCE_{REASONING,EXTRACTION}_LLM_MODEL`, `BLUE_DATA_USER_SOURCE_LLM_MODEL`, `BLUE_DATA_LLM_MODEL`, then the provider's default. User-source passes the resolved model to the KB's agents, rather than leaving them to the KB's own configuration.

**Rationale:** blue-data 1.0 made the family model belong to the family provider, and blue-data-ops, the planner, llm-source and blue-data-kb-source (its ADR-038) reach every provider through LiteLLM. User-source built `openai.AsyncOpenAI()` unconditionally, so a deployment set up for Claude could not run it; #175 only stopped the Claude model from being sent to OpenAI. Pinning the provider keeps a model string from choosing its own route. Blank means `openai`, as in ops and kb, so existing OpenAI setups keep working; blue-data's spec calls blank "deterministic-only", which no part of user-source can be.

**Consequences:**
- `litellm>=1.102,<1.106` is a dependency of the library (kb-source's range: 1.106 needs mcp 2.x), and kb-source is installed with its `[llm]` extra.
- Document embeddings stay on the OpenAI SDK, so the default `openai` document embedding still needs `OPENAI_API_KEY` under any provider.
- JSON mode is OpenAI's: LiteLLM drops a schemaless `response_format` for Anthropic, so `_llm_complete` reads a JSON object out of fences or surrounding prose too.
- The CLI's model parameters inherit `BLUE_DATA_LLM_MODEL` again, and `profile inspect` shows the provider's default for an unset model.
- The benchmark harness records calls by patching both packages' `llm.AsyncClient`.


---

## ADR-029 — `console` Defaults to False and Is Never Part of `properties`

**Date:** 2026-10-31
**Status:** Accepted (supersedes #189's terminal-based default)

**Decision:** `UserSource`'s `console` property defaults to `False`. A caller that owns the terminal and wants the user asked on it passes `console=True`: the CLI does when its stdin is a terminal. The constructor takes `console` out of the properties it is given and holds it as `UserSource.console`, so it is never in `self.properties`, which blue-data's `DataRegistry.register_source` stores as the source's record. A properties dict that carries `_class` is such a record being rebuilt, and a `console` in it, left by an older version, is ignored (#191).

**Rationale:** #189 took "stdin and stdout are terminals" as "a user is at this console". That is false for a server started in the foreground of a terminal: a `blue-data-api` hosting a rebuilt source printed a clarification prompt on the server's terminal, and the REST request waited for it. And `console=True` given by an interactive script was stored in blue-data's registry, so every host rebuilt the source with it, including `blue-data-registry-mcp` on stdio (#186 again). Only the program that owns the terminal can know a person is at it; a library cannot tell from the streams.

**Consequences:**
- Library scripts that relied on being asked at the terminal pass `console=True` (the examples that do now do).
- A registry host never asks on the console, whatever its streams, and needs no change. blue-data's side (megagon-internal/blue-data#250) is no longer needed for user-source, though a per-process property hook there would still help other sources.



---

## ADR-030 — Benchmark Results Are a Committed History per Module, with the Baseline Flagged in It

**Date:** 2026-11-02
**Status:** Accepted (supersedes #131's `baseline.json` and per-snapshot `README.md`)

**Decision:** Each benchmark module keeps `lib/tests/benchmarks/<module>/results/history.jsonl`, one summary line per full live run (commit, models, value per case and per group, tokens, latency, note), and `results/README.md` rendered from it with trend charts, as blue-data-kb-source keeps its extraction benchmark's. The live runners append to it at the end of every full-suite run. The regression baseline is the run flagged `"baseline": true` in the module's history (`python -m tests.benchmarks.common.history baseline`), not a separate `baseline.json`. Snapshot directories under `tests/benchmarks/results/` keep only the full score reports and `run.json`.

**Rationale:** The committed results were one hand-written snapshot and a baseline built from it: seeing a trend meant reading several snapshots side by side, and a new baseline needed a hand-written summary first. The history records every full run at no cost, and the generated page shows the change since the last run per case and per group. `baseline.json` held the same per-case values as a history line, so it was a second copy that could drift.

**Consequences:**
- A full live run changes two committed files; commit them to keep the run, or pass `--no-history`.
- The 2026-10-10 gpt-4o run is in each module's history, flagged as the baseline, with its snapshot's notes; its per-case values are those of the removed `baseline.json`.
- Snapshot directories are optional and are linked from their history lines.
