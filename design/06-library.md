# UDb — Library

> External dependencies: `blue-data-core` provides `DataSource`, `FileSource`, `SessionSource`, `Session`, `DataPlanner`, `DataRegistry`, and related base classes.

---

## UserSource(DataSource)

Entry point for all UDb operations. Holds a `UserQueryReasoner` for reasoning and a `UserDataManager` for data operations.

### Constructor

```python
UserSource(properties={})
```

### Example

```python
us = UserSource(properties={})

eser_db = "5WgRzdacRdOEvj8JBmCXFZSvWmH3"
us.create_database(eser_db)

# Type 1 import — register source for later querying
fs = FileSource("~/resume.txt")
us.import(fs, database=eser_db)

# Type 2 import — extract structured data from source
us.import(fs, database=eser_db, optional_properties={"queries": ["what skills does user have?"]})

# Import active session as a streaming source
session = Session()
ss = session.get_source()
us.import(ss, database=eser_db)

# Query
results = us.execute_query(
    "jobs suitable for me",
    database=eser_db,
    optional_properties={"session": session.cid}
)
```

### Methods

#### `execute_query(query, database=None, optional_properties={})`

Executes a natural language query against a user database.

**Parameters**

- `query` — natural language query; may be partial or complete
- `database` — user database identifier
- `optional_properties`:
  - `"session"` — session ID; used as query context and as the primary contact method for user 
  interaction
  - `"output"` - output format; defaults to JSON, other options include "NL", "CSV", etc.
  - `"prompt"` - prompt to translate structured data to natural language

**Returns**

List of result objects, one per question in the resolved question set:

```python
[{"query": "<question>", "results": [...]}, ...]
```

Includes the original query if it has full coverage, plus any complementary queries that were necessary.

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

#### `create_user(name)`

Delegates to `UserDataManager.create_user(name)`.

#### `create_database(name)`

Alias for `create_user(name)`.

---

## UserQueryReasoner

Encapsulates query rewriting, metric-based result assessment, and user interaction coordination for a specific user database. Instantiated per `execute_query` call. Instantiates `ContactManager` when user interaction is required.

### Constructor

```python
UserQueryReasoner(source, database)
```

Instantiates with a set of `UserDataMetric` instances.

**Parameters**

- `source` — the parent `UserSource` instance
- `database` — user database identifier

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

1. Call `UserDataPlanner.plan(query, database)` to decompose the query into subqueries and identify relevant sources for each
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

Produces an execution plan for a query by decomposing it into subqueries and mapping each to relevant sources in the registry.

### Methods

#### `plan(query, database)`

Returns an execution plan: a list of `(subquery, source)` pairs derived from sources registered in `UserDataRegistry` for the given user.

---

## UserDataRegistry(DataRegistry)

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

Supported protocols: `session`, `email`, `sms`, `stdio`, messaging applications, enterprise messaging systems, notifications.

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

#### `send(message, async=False)`

Sends a message to the user.

- `async=False` — blocks and returns the user response directly
- `async=True` — returns a `Future` to be awaited

Calls `_on_response()` on receipt.

#### `_on_start()`

#### `_on_response(message)`

#### `_on_stop()`
