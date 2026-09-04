# UDb — Detailed Architecture

## External Interfaces

All four interfaces are thin adapters over the Python library. They each ultimately delegate to `UserSource.execute_query()` and `UserSource.import()`.

| Interface | Technology | Primary Use |
|-----------|-----------|-------------|
| Python Library | Native Python API | Embedding UDb in Python applications |
| MCP Server | MCP protocol | LLM agent tool use (e.g. Claude) |
| REST API | FastAPI (HTTP/JSON) | Non-Python consumers and microservice deployments |
| CLI | Click + Rich | Development, debugging, and scripting |

### Python Library

`UserSource` and related classes are the native interface. Direct method calls with no serialization overhead. All other interfaces wrap this layer.

### MCP Server

Exposes `execute_query` and `import` as MCP tools, allowing LLM agents to query and populate UDb directly within an agentic context.

### REST API

HTTP interface built with FastAPI. Endpoints map 1:1 to `execute_query` and `import`. Enables non-Python services and remote clients to interact with UDb.

### CLI

Command-line interface built with Click and Rich. Thin wrapper over the Python library for interactive use, scripting, and development workflows.

---

## Information Flow Overview

### Query Path

1. NLQI receives `query()`, forwards to Reasoning Layer
2. Reasoning Layer rewrites query, expands into question set Q
3. For each qi in Q: DML retrieves data di, Reasoning Layer evaluates metrics Mi
4. If Mi falls below thresholds: Interaction Layer clarifies with user, returns updated data for reassessment
5. Reasoning Layer aggregates all resolved (qi, di, Mi) into final response
6. Response returned through NLQI to caller

### Import Path — Type 1: Source Registration

1. NLQI receives `import(source)`
2. DML registers source in Source Manager as user metadata
3. Source becomes immediately available for future queries

### Import Path — Type 2: Query-over-Source

1. NLQI receives `import(source, query)`
2. Reasoning Layer executes query over the imported source via DML
3. Extracted results are injected into user data
4. Source optionally registered for future queries

Entity extraction from an uploaded file (e.g., resume parsing) is an instance of Type 2.

---

## 1. Natural Language Query Interface (NLQI)

The NLQI layer is the entry point for all requests to UDb. It receives and routes incoming requests without performing query interpretation itself.

### Responsibilities

- Receive incoming requests
- Route `query()` and `import()` to the appropriate processing path
- Maintain session context for the duration of the request

### Query Intake

Receives:

- `query()` — natural language retrieval request
- `import()` — data ingestion request (source registration or query-over-source)

Examples:

- `"jobs suitable for me"`
- `"what skills do I have?"`
- `"find management roles for me"`

---

## 2. Reasoning Layer

The Reasoning Layer orchestrates query rewriting, retrieval coordination, quality evaluation, and iterative refinement. It determines whether the system knows enough to confidently answer the query.

### Responsibilities

- Rewrite and expand incoming queries
- Coordinate question execution across the DML
- Evaluate data quality
- Determine whether user clarification is needed
- Drive iterative refinement loops
- Aggregate final responses

### Query Rewriter

Transforms the original query into a normalized query and an expanded question set.

**Example**

Input: `"jobs suitable for me"`

Rewritten query: `"What jobs are suitable for this user?"`

Expanded question set Q:

- `"What skills does the user have?"`
- `"What titles is the user interested in?"`
- `"Does the user have location constraints?"`
- `"What is the user's expected compensation?"`
- `"Does the user prefer remote work?"`

**Context Expansion Sources**

- User profile
- Session history — the current session's own prior queries and resolved interactions, tracked by the Session Manager (below)
- Previous interactions — resolved Q/A transcripts, ingested into the session's `DocumentDataSource` for semantic recall (below)
- Historical preferences
- Organizational knowledge
- Domain templates

**Current implementation** — `UserQueryReasoner.contextualize_query` rewrites the query into a well-formed question with every self-reference to the user (`"you"`, `"your"`, `"the user"`, pronouns, the user's own name, …) replaced by the user's actual name from `identity.name`, so the KB agent sees an unambiguous third-person question. `expand_query` then decomposes the rewritten query into standalone, third-person sub-questions grounded in the facets the KB schema can actually answer (entity attributes and relations, exported via `KBSource.export_database_schema`) — it never invents clarification-style questions ("do you...", "would you..."), never repeats the original query or another sub-question, and returns an empty list (not the original query) when the query is already a single specific lookup, capped at 5 sub-questions otherwise. Of the sources listed above, only the KB schema itself is currently wired in as expansion context; session history, prior interactions, historical preferences, organizational knowledge, and domain templates remain aspirational.

### Processing Flow

For each question qi in Q:

1. Execute qi through the Data Management Layer
2. Receive result di
3. Evaluate quality metrics Mi via the Data Assessor
4. If Mi falls below thresholds, forward (qi, di, Mi) to Interaction Layer
5. Repeat until metrics are satisfactory

Result tuple: **(qi, di, Mi)**

| Symbol | Meaning |
|--------|---------|
| qi | Question |
| di | Retrieved data / result |
| Mi | Metric scores |

### Data Assessor

Evaluates the quality and validity of retrieved data.

**Responsibilities**

- Assess completeness
- Assess freshness
- Assess confidence
- Assess consistency
- Assess relevance
- Detect ambiguity
- Determine sufficiency thresholds

**Metrics**

| Metric | Description |
|--------|-------------|
| Completeness | Is enough information available? |
| Freshness | Is the information recent? |
| Confidence | How reliable is the evidence? |
| Consistency | Do sources agree? |
| Relevance | Is the information relevant to the query? |
| Specificity | Is the information sufficiently detailed? |

**Example**

For `"Suitable jobs for me"`:

| Metric | Score |
|--------|-------|
| Completeness | 0.45 |
| Freshness | 0.92 |
| Confidence | 0.78 |
| Relevance | 0.88 |

Completeness is below threshold → interaction required.

**Current implementation** — each `UserDataMetric` compares its score against `_threshold()`, which defaults to the class-level `THRESHOLD` (0.6). `PrivacyMetric` overrides `_threshold()` to move the bar with the user's `privacy.consent_level`: `minimal` consent raises it to 0.8 (stricter — less tolerance for privacy risk), `full` consent lowers it to 0.4, `standard` (or an unset/unrecognized level) keeps the default 0.6.

**Satisfaction Evaluation**

The Reasoning Layer determines:

- Whether all metrics exceed thresholds
- Whether missing information can be inferred
- Whether user interaction is necessary

If satisfactory: aggregate and return final evidence-backed results.
Otherwise: forward unresolved (qi, di, Mi) to the Interaction Layer.

**Current implementation** — the assess-then-interact cycle described above (steps 3-5 of the Query Path, and this section's Processing Flow) is owned end-to-end by `UserQueryReasoner.resolve_via_interaction`, called once by `UserSource._run_query` after aggregating results across all sub-questions (not per sub-question): it evaluates metrics, and while any fail, calls `request_user_interaction` and re-evaluates the augmented result, up to `max_interaction_rounds` (default 3, an `optional_properties` key on `execute_query`) — stopping as soon as every metric passes. Only the user's newly-collected responses (one per round) are surfaced back as a `QueryResult`, not the full augmented data list.

---

## 3. Interaction Layer

The Interaction Layer handles clarification, verification, and conversational refinement through the most appropriate communication channel.

### Responsibilities

- Determine contact strategy
- Generate clarification prompts
- Manage conversations
- Capture user responses
- Re-trigger assessment in the Reasoning Layer
- Support iterative refinement

### Interaction Flow

Input: **(qi, di, Mi)**

The layer:

1. Selects communication channel via Contact Manager
2. Mints an `interaction_id` via the Session Manager, recording the interaction as `"pending"` under the current session/query
3. Generates clarification request via Interaction Manager, passing the same `interaction_id` so the transport-level correlation and the durable record share one id
4. Sends interaction to user
5. Waits for response
6. Records the response via the Session Manager (`"resolved"`, or `"timeout"` if the wait fails) and ingests the transcript into the session's `DocumentDataSource`
7. Returns updated data to Reasoning Layer for reassessment
8. Repeats if necessary

### Contact Manager

Selects the most appropriate communication mechanism.

**Responsibilities**

- Manage available communication channels
- Maintain communication preferences
- Rank and select optimal contact method

Session tracking itself — which sessions are active, what they contain — is owned by the Session Manager below, not the Contact Manager; the Contact Manager only picks *how* to reach the user for a given interaction.

**Supported Channels**

- Active conversational session
- Email
- Messaging applications
- SMS
- Enterprise messaging systems
- Notifications

**Example Decision**

If user is currently active → use active chat session.
Otherwise → send email or asynchronous notification.

**Current implementation** — `ContactManager.identify_contact_method` returns the sole contact method directly when only one is registered; otherwise `_choose_contact_method` asks an LLM to pick among the options, giving it each method's stated `preference`, whether it is asynchronous (`ContactMethod.is_async` — true for `email`/`webhook`/`notification`), the user's stated `preferred_channel` and `working_hours` (`availability.*`), the current time localized to `identity.timezone`, whether that time falls within the stated working hours (best-effort parse of free-text windows like `"09:00-17:00 Mon-Fri"`), and whether the user is currently `out_of_office`. The LLM is instructed to prefer an asynchronous method when the user is out of office or outside working hours; if the call fails or returns an unrecognized choice, the fallback is the lowest-`preference` method — restricted to asynchronous methods when `out_of_office` is true and at least one exists. An optional `topic` argument looks up `availability.by_topic.<topic>` overrides (`working_hours`, `preferred_channel`, `out_of_office`) layered on top of the general `availability.*` settings, so different projects/topics can have different reachability rules.

### Interaction Manager

Coordinates conversational clarification.

**Responsibilities**

- Generate clarification prompts
- Contextualize follow-up questions
- Manage interaction state
- Await user responses
- Feed new data back to Reasoning Layer

**Example**

Input: (qi, di, Mi)

Generated questions:

- `"Do you prefer remote work?"`
- `"Would you consider staff-level roles?"`
- `"Do you have location restrictions?"`

The Interaction Manager then:

1. Sends the message
2. Waits for user response
3. Updates context
4. Triggers reassessment in the Reasoning Layer

### Session Manager

Tracks sessions, and the queries and interactions within them, as a durable record — per-user, mirroring the Contact Manager's storage pattern (a `sessions` JSONSource in the per-user DataRegistry, dotted-path CRUD).

**Responsibilities**

- Create sessions and mint session ids
- Record each external query appended to a session
- Record each clarification interaction (question, response, contact method used) under its query
- Mint `interaction_id`s that double as the transport-level correlation key the Interaction Manager uses to wait for a reply
- Ingest resolved interaction transcripts into a per-session `DocumentDataSource`, for later semantic recall as a Context Expansion Source
- End sessions

**Reuse-or-create at the query boundary**

`UserSource._run_query` (the shared implementation behind `execute_query`/`execute_query_nl`) decides session continuity before invoking the Reasoning Layer: if the caller supplied a session id, the query is appended to that session (or rejected if it doesn't exist or has ended); otherwise a fresh single-query session is created automatically. This means a caller that wants a multi-query conversation must pass back the `session_id` it received from a prior call — the Session Manager itself never guesses at continuity.

**Session lifecycle**

```
active ──(end_session)──> ended
```

An ended session accepts no further queries; `create_query` raises. There is no automatic expiry — sessions stay `"active"` until explicitly ended.

**Relationship to Contact Manager**

The Contact Manager and Session Manager are used together but track different things: Contact Manager picks *which* channel to use for a given interaction; Session Manager records *that* the interaction happened, what was asked, what was answered, and ties it back to the session and query it belongs to. See §6 of [10-data-model.md](10-data-model.md) for the exact record schema.

---

## 4. Data Management Layer (DML)

The Data Management Layer handles source discovery, retrieval planning, query execution, and result aggregation across heterogeneous data sources.

### Responsibilities

- Discover relevant data sources
- Plan retrieval strategies
- Execute structured data operations
- Aggregate evidence
- Normalize results
- Support provenance tracking
- Register new sources on import

### import() Handling

**Type 1 — Source Registration**

The imported source is registered in the Source Manager as part of user metadata. It becomes available for future queries via the Query Planner.

**Type 2 — Query-over-Source**

A query is executed over the imported source by the Reasoning Layer via the DML. Extracted results are injected into user data. Entity extraction from an uploaded file is an instance of this type.

### Query Planner

Interprets an incoming query, discovers relevant sources, and produces an execution plan.

**Responsibilities**

- Interpret query intent
- Discover candidate sources via Source Manager
- Build execution plan
- Select retrieval operators
- Optimize execution strategy

**Example Plan**

For `"Suitable data science jobs"`, the planner may:

- Inspect user resume
- Inspect historical preferences
- Inspect prior job interactions
- Retrieve location preferences
- Aggregate role preferences

### Query Executor

Executes plans produced by the Query Planner.

**Responsibilities**

- Execute retrieval operations
- Coordinate operators
- Aggregate results
- Compute evidence
- Track provenance
- Normalize outputs

**Example Output**

```
(source, evidence, timestamp, confidence)
```

**Current implementation** — `UserDataManager.execute_query` is the concrete Query Executor for one sub-question: it calls `KBSource.answer()` against `kb`, then runs `DOCUMENT.SEARCH` against `session_content` and `external_documents`, merging all three into one `(data, metadata)` result (each document hit tagged `"source": "session_content" | "external_documents"`). See ADR-019 in [13-decision-log.md](13-decision-log.md). Aggregation across heterogeneous sources happens here, per sub-question — not, as §2's Context Expansion Sources list still describes, at Query Rewriter time; that use of `session_content` is not yet implemented.

### Source Manager

Maintains the registry of all data sources available for a user. Serves as the UDb-specific data registry (referred to as "Registry" in the High Level Architecture).

**Responsibilities**

- Maintain source registry
- Store source metadata
- Manage schemas
- Track access methods
- Register new sources on import
