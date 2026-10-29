# Architecture

## Overview

`blue-data-user-source` has two tiers:

- **`lib/`** — the core Python library (`UserSource` and its per-user managers)
- **`platform/`** — deployable components built on top of `lib/` (CLI, MCP server, REST API)

### lib/ core

```
                   External Interfaces

        ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
        │ Python Lib  │  │ MCP Server  │  │  REST API   │  │     CLI     │
        └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
               └────────────────┴────────────────┴────────────────┘
                                        │
                                        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                                  UserSource                                  │
│                     (outer registry — one entry per user)                    │
└───────────────────────────────────────┬──────────────────────────────────────┘
                                        │  per user
                                        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Per-user DataRegistry                                │
│                                                                                │
│  ┌────────────────────────────┐   ┌────────────────────────────────────────┐ │
│  │      UserQueryReasoner      │   │           UserDataManager               │ │
│  │  ┌────────────────────┐    │   │  ┌────────────────────────────────┐    │ │
│  │  │ contextualize_query │    │   │  │  kb (KBSource)                  │    │ │
│  │  │ expand_query        │    │   │  │  metadata (JSONSource)          │    │ │
│  │  │ assess_query_results│    │   │  │  contacts (JSONSource)          │    │ │
│  │  │ resolve_via_        │    │   │  │  sessions (JSONSource)          │    │ │
│  │  │   interaction       │    │   │  │  session_content (DocDataSource)│    │ │
│  │  └────────────────────┘    │   │  │  external_documents (DocData…)  │    │ │
│  └──────────────┬─────────────┘   │  └────────────────────────────────┘    │ │
│                 │                 └────────────────────────────────────────┘ │
│        ┌────────▼─────────┐                                                  │
│        │  ContactManager    │  ┌─────────────────┐                          │
│        │  SessionManager     │  │ UserDataMetric   │ Completeness/Freshness/ │
│        │  InteractionManager │  │   × N            │ Privacy                 │
│        └────────────────────┘  └─────────────────┘                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

`UserSource` is abstract over how the outer registry (the list of user names) is stored; `MemoryUserSource`, `FileUserSource`, and `RedisUserSource` are ready-made backends (see [Backends](#backends) below). Each user gets its own `DataRegistry` — a separate `KBSource`, three `JSONSource`s, and two `DocumentDataSource`s — built or reconnected on first use.

| Component | Module | Role |
|---|---|---|
| `UserSource` | `source.py` | Entry point; manages the outer user registry, dispatches to per-user managers |
| `UserQueryReasoner` | `reasoning/reasoner.py` | Query rewriting, expansion, metric assessment, and the interaction loop |
| `UserDataMetric` | `reasoning/metric.py` | `CompletenessMetric`, `FreshnessMetric`, `PrivacyMetric` — one quality dimension each |
| `UserDataManager` | `data/manager.py` | Owns the per-user `DataRegistry`; builds/connects/resets/destroys its sources; executes per-sub-question retrieval |
| `UserDataPlanner` | `data/planner.py` | Placeholder, not on the query path in 1.0 — see below |
| `ContactManager` / `ContactMethod` | `interaction/contact.py` | Contact-method CRUD and channel selection; per-protocol interaction setup |
| `SessionManager` | `interaction/session.py` | Session/query/interaction record lifecycle |
| `InteractionManager` | `interaction/manager.py` | Drives one interaction's start/send/stop lifecycle for a chosen channel |

### platform/ layer

```
  ┌───────────────────────────────────────────────────────────────────────────┐
  │                          platform/ components                             │
  │                                                                           │
  │  ┌────────────────┐   ┌────────────────┐   ┌────────────────────────┐    │
  │  │      cli        │   │      mcp        │   │         api             │  │
  │  │ (Click + Rich)  │   │ (FastMCP server) │   │ (FastAPI + Uvicorn)    │  │
  │  │ terminal, one   │   │ stdio/MCP        │   │ HTTP/JSON, 20+ routes  │  │
  │  │ FileUserSource  │   │ protocol, 23     │   │ over one FileUserSource│  │
  │  │ per invocation   │   │ tools            │   │ per process             │  │
  │  └────────┬─────────┘   └────────┬─────────┘   └───────────┬────────────┘  │
  │           │                      │                          │              │
  │           │     (no shared state — each owns its own FileUserSource,       │
  │           │      configured from BLUE_DATA_USER_SOURCE_* independently)    │
  │           └──────────────────────┴──────────────┬───────────┘              │
  │                                                  ▼                          │
  │                                            UserSource                       │
  └───────────────────────────────────────────┬─────────────────────────────────┘
                                              │  Python import
                                              ▼
                                    lib/src/blue_data_user_source/
```

| Component | Entry point | Transport | Status |
|---|---|---|---|
| `cli` | `platform/cli/` (`blue-userdb`) | Terminal (Click) | Implemented |
| `mcp` | `platform/mcp/` (`blue-userdb-mcp`) | stdio (MCP) | Implemented |
| `api` | `platform/api/` (`blue-userdb-api`) | HTTP (FastAPI) | Implemented |

All three processes are independent — none shares state with another, and each holds its own `FileUserSource` instance configured from `BLUE_DATA_USER_SOURCE_*` environment variables (`cli` also layers `--database`/`--data-dir`/`--schema-path` flags on top). Pointing all three at the same `BLUE_DATA_USER_SOURCE_DATA_DIR` (the shared `~/.blue-userdb` default) gives practical, not automatic, continuity between them — a user created via `blue-userdb database create` is visible to `blue-userdb-mcp`/`blue-userdb-api` reading the same directory.

---

## Reasoning Layer

`UserQueryReasoner`, instantiated per `execute_query` call, owns query rewriting, expansion, and the assess-interact-reassess loop.

**`contextualize_query`** rewrites the query into a well-formed question with every self-reference to the user (`"you"`, `"your"`, `"the user"`, pronouns, the user's own name) replaced by the user's actual name (`identity.name`, falling back to the database id), so downstream stages see an unambiguous third-person question.

**`expand_query`** decomposes the rewritten query into standalone, third-person sub-questions grounded in the facets the KB schema can actually answer (entity attributes and relations, via `KBSource.export_database_schema`) — never clarification-style questions, never a repeat of the original or another sub-question, capped at 5, and an empty list when the query is already a single specific lookup.

**Metric assessment.** Each `UserDataMetric` (`CompletenessMetric`, `FreshnessMetric`, and `PrivacyMetric` when a data manager is available) scores the combined result and compares it against `_threshold()` (default 0.6). `PrivacyMetric` moves its own threshold with `privacy.consent_level`: 0.8 at `minimal`, 0.4 at `full`, 0.6 otherwise.

**`resolve_via_interaction`** owns the full cycle end-to-end: evaluate metrics, and while any fail, ask the user for clarification (via `request_user_interaction`) and re-evaluate the augmented result — up to `max_interaction_rounds` (default 3) times, stopping as soon as everything passes. Each non-blank reply is added to the evidence with provenance of its own (`user-reply:<interaction_id>`: source `user via <protocol>`, the question and answer as its content, timestamped now), and `FreshnessMetric` sees every node's source and content as well as its age, so a user confirming or correcting old information makes it current — without this, a clarification could fix completeness but never freshness. Called once by `UserSource._run_query` after aggregating results across all sub-questions, not per sub-question. Only the newly collected responses are surfaced back as a `QueryResult`.

---

## Data Management Layer

`UserDataManager` owns one user's `DataRegistry` — a `KBSource` (`"kb"`), three `JSONSource`s (`"metadata"`, `"contacts"`, `"sessions"`), and two shared `DocumentDataSource`s (`"session_content"`, `"external_documents"`) built via `.build()` for a new user or reconnected lazily via `.connect()`.

`execute_query(query, session_id=None)` is the per-sub-question retrieval step the reasoning layer calls once per expanded question:

```
UserDataManager.execute_query(query, session_id)
  → KBSource.answer(database, query, include_metadata=True)      # knowledge graph
  → DOCUMENT.SEARCH against "session_content"                    # top 5 chunks
  → DOCUMENT.SEARCH against "external_documents"                 # top 5 chunks
  → merge into one (data, metadata); each doc hit tagged
    "source": "session_content" | "external_documents"
```

`UserDataManager` is the executor for one sub-question: it always searches the KB, `session_content` and `external_documents`, as above. There is no per-source planning. `UserDataPlanner` exists but is a placeholder: not used by the query path in 1.0: `plan` returns the query unchanged, once per registered source, and `UserSource` never calls it. Query decomposition is done by `UserQueryReasoner.expand_query` (LLM sub-questions), and every sub-question is answered from the same fixed set of stores. Real source selection is future work (#128).

---

## Query Path

```
UserSource.execute_query(query, database, optional_properties)
  → _run_query(...)
      1. resolve session: reuse the given "session" id, or auto-create a single-query one
      2. reasoner.contextualize_query(query)               → rewritten query
      3. reasoner.expand_query(rewritten)                  → sub-questions (possibly empty)
      4. for each sub-question:
           data_manager.execute_query(sub_question, session_id) → (data, metadata)
         merge all sub-question results
      5. reasoner.resolve_via_interaction(query, rewritten, data, metadata,
                                           max_rounds=max_interaction_rounds)
           → assess metrics; while failing, contact_manager.identify_contact_method()
             asks the user, session_manager records the interaction, reassess
      6. return list[QueryResult] (or a synthesized NL string), session_id
```

## Import Path

**Type 1 — source registration only.** `add_source(source, database)` with no `queries`: the file is parsed, chunked, and embedded into the shared `external_documents` `DocumentDataSource`. It becomes searchable and contributes to future query results, but nothing is written to the knowledge graph.

**Type 2 — query-over-source.** `add_source(source, database, optional_properties={"queries": [...]})`: does everything Type 1 does, plus runs one `KBSource.import_text` LLM-extraction call per query, writing extracted entities/facts/properties into the KG.

---

## Interaction Layer

`ContactManager.identify_contact_method(topic=None)` returns the sole registered method directly when there's only one; otherwise an LLM picks among them, weighing each method's `preference`, whether it's asynchronous (`ContactMethod.is_async` — true for `email`/`webhook`/`notification`), the user's `preferred_channel`/`working_hours` (`availability.*`, localized to `identity.timezone`), and whether `out_of_office` is set — preferring an asynchronous method when the user is unavailable. On LLM failure (`LLMError`) it falls back to the lowest-`preference` method — the one LLM call with a fallback; every other one lets `LLMError` propagate, so an outage is never reported as an empty result (asynchronous-only, if any, when out of office). `topic` layers `availability.by_topic.<topic>` overrides on top of the general settings.

Methods whose protocol has no transport in this release (`sms`, `messaging`, `enterprise`, `notification`, `session` — recorded only) are never candidates. With no usable methods registered it falls back to `stdio` — but only when the process has a console (`ContactManager(..., console=True)`, from the `UserSource`'s `console` property). Without one (the REST and MCP servers), methods that ask on stdin/stdout are filtered out first, and if nothing is left it returns `None`: the reasoner then stops the clarification loop and returns the results it has (`NoContactMethodError` from `request_user_interaction`), and onboarding is skipped.

`SessionManager` (per-user, via the `"sessions"` `JSONSource`) mints session/query/interaction ids and records each round-trip's question, response, contact method, and lifecycle status (`"pending"` → `"resolved"`/`"timeout"`/`"failed"`; a timed-out or undeliverable question ends the clarification loop and the query returns what it retrieved). Resolved interactions are also ingested as `"Q: ...\nA: ..."` text into the session's `DocumentDataSource` for later semantic recall.

`InteractionManager` drives one interaction's `start()`/`send()`/`stop()` lifecycle for the channel `ContactMethod.interact()` returns — `stdio` blocks on stdin, `email`/`webhook` await an async reply correlated by `interaction_id` through a shared `pending_interactions` Future registry (see [extending.md](extending.md#adding-a-contact-method-protocol)).

---

## Backends

### Outer registry (`UserSource`)

| Backend | Class | Persistence | Typical use |
|---|---|---|---|
| Memory | `MemoryUserSource` | None (in-process) | Testing, short-lived pipelines |
| File | `FileUserSource` | One `registry.json` | CLI/MCP/API default — no server required |
| Redis | `RedisUserSource` | Redis JSON | Multi-process / shared deployments |

Each mixes in a different `JSONSource` for the registry (`MemoryJSONSource`/`FileJSONSource`/`RedisJSONSource` from `blue-data`) and reports its own `user/memory`/`user/file`/`user/redis` connection protocol.

The protocol follows the family-wide `<family>/<backend>` convention, but for a composite source the second segment needs reading with care: it names the **outer registry's** backend — the catalog of which users exist — not the storage behind any one user. The per-user `kb`/`metadata`/`contacts`/`sessions`/`documents` backends are chosen at `create_user` time, may differ between users of the same source, and each carries its own honest protocol (`kb/file`, `json/file`, `vector/file`) in its own source record. The base `UserSource` has no registry backend of its own, so it reports the family alone: `user`.

### Per-user knowledge graph (`UserDataManager`'s `"kb"` source)

| Backend | Class path | Notes |
|---|---|---|
| Memory | `blue_data_kb_source.memory_kb_source.MemoryKBSource` | No persistence |
| File | `blue_data_kb_source.file_kb_source.FileKBSource` | One JSON file per user — CLI default |
| Neo4j | `blue_data_kb_source.neo4j.neo4j_kb_source.NEO4JKBSource` | Requires `blue-data-kb-source[neo4j]` |

### Per-session/external document stores

`session_content` and `external_documents` are `DocumentDataSource`s (from `blue-data-doc-source`), each with its own embedding model + vector backend, configured once via `doc_source_props` at `create_user` time and recorded with the user: an embedding, a search mode (`vector`, `hybrid` or `bm25`) and a vector store. New users get OpenAI embeddings searched by vector; the library keeps the vector store in memory, and the CLI, MCP and API keep it in files so transcripts and ingested files survive restarts. The `dummy` embedding is a hash, so it is only allowed with `bm25`, and doc-source keeps its BM25 corpus in the ingesting process only: keyword search finds nothing after a restart. Unlike `kb`/`metadata`/`contacts`/`sessions`, these are not reconstructed through the registry's generic `_class`/`connection` reflection — `UserDataManager` rebuilds and caches them itself, since a live embedding-model object can't round-trip through that mechanism.
