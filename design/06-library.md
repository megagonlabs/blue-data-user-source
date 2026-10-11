# UDb — Library

> External dependencies: `blue-data` provides `DataSource`, `JSONSource` and `DataRegistry`; `blue-data-kb-source` provides `KBSource`; `blue-data-doc-source` provides `DocumentDataSource`. The `FileSource`, `SessionSource`, `Session` and `DataPlanner` classes this spec originally assumed do not exist: files are passed as paths, and sessions are records kept by the Session Manager.
>
> This is the design-level specification. Where 1.0 differs, a **Current implementation** note says how; the exact signatures are in [09-api-interface-spec.md](09-api-interface-spec.md).

---

## UserSource(DataSource)

Entry point for all UDb operations. Holds a `UserQueryReasoner` for reasoning and a `UserDataManager` for data operations.

### Constructor

```python
UserSource(properties={})
```

### Example

```python
us = MemoryUserSource("blue-userdb")   # or FileUserSource / RedisUserSource

await us.create_user("alice", ...store configs..., onboard=False)

# Type 1 — add a file for later querying
await us.add_source("resume.txt", database="alice")

# Type 2 — also extract structured data from it
await us.add_source("resume.txt", database="alice",
                    optional_properties={"queries": ["What skills does the user have?"]})

# Query in a session
session_id = await us.create_session("alice")
answer, session_id = await us.async_execute_query(
    "jobs suitable for me",
    database="alice",
    optional_properties={"session": session_id},
)
```

There is no streaming session source: a session's clarification transcripts are ingested automatically into the `session_content` document store and searched at query time.

### Methods

#### `execute_query(query, database=None, collection=None, optional_properties=None)`

Executes a natural language query against a user database.

**Parameters**

- `query` — natural language query; may be partial or complete
- `database` — user database identifier
- `optional_properties`:
  - `"session"` — session ID; used as query context and as the primary contact method for user 
  interaction
  - `"output_form"` - `"json"` (default) or `"nl"`
  - `"include_expanded"`, `"max_interaction_rounds"`, `"model"` — see [09](09-api-interface-spec.md)

**Returns**

List of result objects, one per question in the resolved question set:

```python
[{"query": "<question>", "results": [...]}, ...]
```

Includes the original query if it has full coverage, plus any complementary queries that were necessary.

**Current implementation** — returns `(answer, session_id)`. The answer is synthesized across all sub-questions: one aggregated table (a list of dicts) for `"json"`, prose for `"nl"`. The per-sub-question `{"query", "results"}` list above is returned only with `include_expanded=True`, as `{"result": answer, "expanded": [...]}`. `async_execute_query` is the same call for async callers.

**Algorithm**

1. Instantiate `UserQueryReasoner(source=self, database=database)`
2. Call `reasoner.contextualize_query(query)` to rewrite query for user data context
3. Call `reasoner.expand_query(query)` to produce complementary question set Q
4. For each qi in Q:
   - (a) Call `data_manager.execute_query(qi, database)` → `(qi, di, md_i)`
   - (b) Call `reasoner.assess_query_results(qi, di, md_i)` → metric scores `Mi`
   - (c) Call `reasoner.assess_user_verification(qi, di, md_i, Mi)` → interaction needed?
   - (d) If interaction required: instantiate `ContactManager` and pass `(qi, di, Mi)` to Interaction Layer; repeat until metrics satisfactory
5. Return all resolved `(qi, di, Mi)` as results

**Current implementation** — steps 4(b)–(d) run once over the results of all sub-questions together, not per sub-question, in `UserQueryReasoner.resolve_via_interaction` (see [04](04-detailed-architecture.md) §2); `assess_user_verification` is named `assess_user_interaction`.

#### `import(source, database=None, optional_properties={})`

Imports data from an external source into the user database.

**Parameters**

- `source` — a `DataSource` instance (e.g. `FileSource`, `SessionSource` from `blue-data-core`)
- `database` — user database identifier
- `optional_properties`:
  - `"queries"` — list of natural language queries to execute over the source; only results are imported

**Behavior**

- No queries specified (Type 1): delegates to `UserDataManager.import_source(source, database)` — source is registered in the user's source registry as user-specific metadata
- Queries specified (Type 2): delegates to `UserDataManager.import_source(source, database, queries)` — each query is executed over the source and results are injected into generic user data stores

**Current implementation** — `import` is a reserved word in Python, so the method is `add_source(source, database, optional_properties)` (a file path) and `add_text_source(text, database, optional_properties)` (text, no file). Both always create a KB SOURCE node and ingest the text into `external_documents`; with `queries`, they also extract into the KB. See [04](04-detailed-architecture.md) §4.

#### `create_user(name)`

Delegates to `UserDataManager.create_user(name)`.

#### `create_database(name)`

Alias for `create_user(name)`.

**Current implementation** — `create_user` also takes the store configs for the user's registry, KB, metadata, contacts, sessions and document stores, and onboards the user by default (`onboard=False` skips it). `create_database(name, properties)` is the synchronous `DataSource` form.

---

## UserQueryReasoner

Encapsulates query rewriting, metric-based result assessment, and user interaction coordination for a specific user database. Instantiated per `execute_query` call. Instantiates `ContactManager` when user interaction is required.

### Constructor

```python
UserQueryReasoner(source, manager=None, session_id=None, query_id=None, model="gpt-4o")
```

Instantiates with a set of `UserDataMetric` instances.

**Parameters**

- `source` — the parent `UserSource` instance
- `database` — user database identifier (in 1.0, the user's `UserDataManager` is passed instead)

### Methods

#### `contextualize_query(query)`

Rewrites the query into a clear, well-formed question and replaces every self-reference to the user (`"you"`, `"your"`, `"the user"`, pronouns, the user's own name, …) with the user's actual name from `identity.name`, so the rewritten query is unambiguous when read out of context. References to other people are left unchanged.

**Example (user's name is "Alice"):** `"what is your age"` → `"What is Alice's age"`

#### `expand_query(query)`

Returns a list of standalone, third-person sub-questions that together help answer the original query — never clarification questions addressed to the user. Grounded in the facets the KB schema can actually answer (entity attributes and relations, exported via `KBSource.export_database_schema`) when a data manager is available. Scales to the query's complexity: an already-specific query may expand to an **empty list** rather than padding with filler; a broad query may expand to up to 5 sub-questions.

**Example**

Input: `"jobs suitable for me"` (rewritten to `"What jobs are suitable for Alice?"` by `contextualize_query`)

Output:
```python
[
    "What skills does Alice have?",
    "What titles is Alice interested in?",
    "Does Alice have location constraints?",
    "What is Alice's expected compensation?",
    "Does Alice prefer remote work?"
]
```

#### `assess_query_results(query, query_results, query_results_metadata)`

Returns an aggregate metric evaluation report — score and reasoning per applicable metric. Internally calls `_identify_user_data_metrics` to determine which metrics apply.

#### `assess_user_verification(query, query_results, query_results_metadata, user_data_metric_evaluation)`

Returns a user verification report indicating whether user interaction is required, including score and reasoning.

#### `_identify_user_data_metrics(query, query_results, query_results_metadata)`

Returns the filtered list of `UserDataMetric` instances relevant to the given query and results.

---

## UserDataMetric

An agent that evaluates one quality dimension of query results (e.g. freshness, completeness).

### Constructor

```python
UserDataMetric(properties)
```

### Example

```python
freshness = UserDataMetric(properties)
report = freshness.evaluate(query, query_results, query_results_metadata)
```

### Methods

#### `evaluate(query, query_results, query_results_metadata)`

Returns a metric evaluation report including score and reasoning.

---

## UserDataManager

Manages all data sources for a user database — generic stores and user-specific sources — through a `UserDataRegistry`.

### Constructor

Instantiates a `UserDataRegistry` backed by `JSONSource` and `VectorSource` as generic stores, and prepares the `UserDataPlanner`.

**Current implementation** — the registry is a plain per-user `DataRegistry` holding `kb` (`KBSource`), `metadata`, `contacts` and `sessions` (`JSONSource`), and the `session_content` and `external_documents` document stores. There is no `VectorSource` and no separate user-data JSON namespace; see [10-data-model.md](10-data-model.md).

### Data Model per User

**Metadata** (stored in `JSONSource`):

- General profile (name, picture, last_login, etc.)
- Contact methods (phone number, email address, messaging handles, etc.)
- List of registered user-specific sources (FileSource, SessionSource, etc.)

**Data**:

- Semi-structured data in `JSONSource`
- Vectorized data in `VectorSource`
- Data from registered user-specific sources (FileSource, SessionSource, etc.)

### Methods

#### `execute_query(query, database)`

Executes a query against user data.

**Algorithm**

1. Call `UserDataPlanner.plan(query, database)` to decompose the query into subqueries and identify relevant sources for each (not so in 1.0 — see the status note under [UserDataPlanner](#userdataplannerdataplanner))
2. For each `(subquery, source)` pair in the plan: call `UserDataRegistry.execute(subquery, source)` to retrieve results
3. Aggregate and normalize results into `(q, d, md)` tuples, where `md` includes provenance (source, timestamp, confidence)
4. Return result set

#### `create_user(name)`

Creates a new virtual user database: initializes `JSONSource` and `VectorSource` entries in the registry for the user.

`name` is a unique user identifier.

#### `import_source(source, database, queries=None)`

- `queries=None`: registers `source` in `UserDataRegistry` as a user-specific source (Type 1)
- `queries` provided: executes each query over `source` and inserts results into generic stores — `JSONSource` or `VectorSource` as appropriate (Type 2)

---

## UserDataPlanner(DataPlanner)

> **Status in 1.0:** not implemented as designed. `UserDataPlanner.plan` returns the query unchanged, once per registered source, and the query path does not call it: `UserQueryReasoner.expand_query` decomposes the query into LLM sub-questions, and `UserDataManager.execute_query` answers each from the KB, `session_content` and `external_documents`. See #128.

Produces an execution plan for a query by decomposing it into subqueries and mapping each to relevant sources in the registry.

### Methods

#### `plan(query, database)`

Returns an execution plan: a list of `(subquery, source)` pairs derived from sources registered in `UserDataRegistry` for the given user.

---

## UserDataRegistry(DataRegistry)

> **Status in 1.0:** no subclass; `UserDataManager` uses `blue-data`'s `DataRegistry` directly.

A user-scoped data registry. Maintains all data sources for a given user — generic stores (`JSONSource`, `VectorSource`) and registered user-specific sources — and supports both structured and natural language query execution.

---

## ContactManager

Manages contact methods for a user and selects the most appropriate channel for a given interaction context. Contact method data is stored in user metadata (`JSONSource`).

Instantiated by `UserQueryReasoner` when `assess_user_verification` determines user interaction is required.

### Constructor

```python
ContactManager(database, data_manager)
```

Loads contact methods from user metadata via `UserDataManager`.

### Methods

#### `identify_contact_method(topic=None)`

Returns the `ContactMethod` most suitable right now: the sole registered method if there's only one, otherwise an LLM choice weighing each method's `preference`, whether it's asynchronous, the user's stated `preferred_channel`/`working_hours`/`out_of_office` (`availability.*`, localized to `identity.timezone`), preferring an asynchronous method when the user is out of office or outside working hours. Falls back to the lowest-`preference` method (asynchronous-only, if any, when out of office) on LLM failure. `topic`, if given, layers `availability.by_topic.<topic>` overrides on top of the general `availability.*` settings.

#### `get_contact_methods(name=None, protocol=None)`

Returns all contact methods, optionally filtered by name or protocol.

---

## ContactMethod

Stores metadata for one contact channel and provides access to an `InteractionManager` for that channel.

### Constructor

```python
ContactMethod(details, protocol)
```

Protocols with a transport in 1.0: `stdio`, `email`, `webhook`. Recognized by the contact schema but recorded only (never selected for contact): `sms`, `messaging`, `enterprise`, `notification`, `session`.

### Methods

#### `interact()`

Returns an `InteractionManager` configured for this contact method.

---

## InteractionManager

Manages a single interaction with the user through a specific contact channel. Corresponds to the Interaction Manager component in the architecture.

### Constructor

```python
InteractionManager(on_start, on_response, on_stop)
```

### Methods

#### `start()`

Starts the interaction. Calls `_on_start()`.

#### `stop()`

Ends the interaction. Calls `_on_stop()`.

#### `send(message, blocking=True)`

Sends a message to the user. (`async` is a reserved word, so the flag is `blocking`; `send` itself is a coroutine.)

- `blocking=True` — waits for and returns the user response

**Current implementation** — `blocking` is accepted but unused: every transport waits for the reply (or its timeout).

Calls `_on_response()` on receipt.

#### `_on_start()`

#### `_on_response(message)`

#### `_on_stop()`
