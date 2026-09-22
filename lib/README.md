# blue-data-user-source

Python library for UDb — a multi-user knowledge base with natural language querying, LLM-based extraction, and interactive data quality assurance.

Backed by [blue-data](../blue-data), [blue-data-kb-source](../blue-data-kb-source), and [blue-data-doc-source](../blue-data-doc-source) (per-session interaction transcripts, and files registered via `add_source`).

See [docs/](../docs/README.md) for the full documentation set — [guide.md](../docs/guide.md) for a task-oriented walkthrough and [api-reference.md](../docs/api-reference.md) for the complete method-by-method reference. This README covers installation, a quick usage sample, and running this package's tests.

## Requirements

- Python 3.10+
- OpenAI API key (used by the reasoning and extraction layers)

## Installation

The package is not yet published to PyPI. Install it directly from the local source:

```bash
cd lib
pip install -e .

# With optional extras
pip install -e ".[webhook]"   # outgoing webhook contact method (httpx)
pip install -e ".[email]"     # outgoing email contact method (aiosmtplib)
```

## Development setup

```bash
cd lib
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

### Construct a multi-user source

`UserSource(name, properties)` takes a name and a properties dict. The `"registry"` property points to the JSONSource that backs the outer DataRegistry (where users are registered as databases and schema paths are stored as source properties):

```python
import asyncio
from blue_data_user_source import UserSource

# File-backed (survives process restarts)
us = UserSource("user_source", {
    "registry": {
        "_class": "blue_data.source.json.file_json_source.FileJSONSource",
        "connection": {"protocol": "json/file", "path": "~/.blue-userdb/registry.json"},
    },
    "schema": "data/schema.json",   # optional — used when creating/resetting databases
})

# In-memory (useful for testing)
us = UserSource("user_source", {
    "registry": {
        "_class": "blue_data.source.json.memory_json_source.MemoryJSONSource",
        "connection": {"protocol": "json/memory"},
    },
})
```

### Manage databases

Each database (user) has its own `DataRegistry` backed by a separate JSONSource. The `"registry"` property on each database record is a JSONSource config from which the per-user DataRegistry can be instantiated. The per-user DataRegistry holds the KB source, metadata source, contacts source, and any additional sources added via `add_source`:

```python
async def main() -> None:
    # Create database — builds registry + all built-in sources from scratch, seeds schema
    await us.create_user(
        "alice",
        registry_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb/registries/alice.json"},
        },
        kb_source_props={
            "_class": "blue_data_kb_source.file_kb_source.FileKBSource",
            "connection": {"protocol": "kb/file", "directory": "~/.blue-userdb/sources/alice"},
        },
        metadata_source_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb/sources/alice/metadata.json"},
        },
        contact_source_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb/sources/alice/contacts.json"},
        },
        session_source_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb/sources/alice/sessions.json"},
        },
        # doc_source_props is optional — defaults to a dummy-embedding, in-memory
        # vector backend for per-session interaction transcripts. See "Sessions" below.
    )

    print(us.list_users())       # ["alice"]

    # Reset — clear KB data + imported registry entries, reseed schema
    await us.reset_user("alice")

    # Remove from outer registry only (KB data kept)
    us.remove_user("alice")

    # Remove from outer registry AND wipe all backing files
    await us.delete_user("alice")

asyncio.run(main())
```

### Add sources and query

```python
async def main() -> None:
    await us.create_user(
        "alice",
        registry_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb/registries/alice.json"},
        },
        kb_source_props={
            "_class": "blue_data_kb_source.file_kb_source.FileKBSource",
            "connection": {"protocol": "kb/file", "directory": "~/.blue-userdb/sources/alice"},
        },
        metadata_source_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb/sources/alice/metadata.json"},
        },
        contact_source_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb/sources/alice/contacts.json"},
        },
        session_source_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb/sources/alice/sessions.json"},
        },
    )

    # Type 1 — register a file (.txt/.pdf/.docx); always parsed, chunked, and
    # embedded into the shared "external_documents" DocumentDataSource
    await us.add_source("resume.txt", database="alice")

    # Type 2 — same ingestion, plus extract specific knowledge via LLM into the KG
    await us.add_source(
        "resume.txt",
        database="alice",
        optional_properties={"queries": ["What skills does the user have?"]},
    )

    # Remove a source from the registry (KG data is preserved)
    us.remove_source("alice", "resume.txt")

    # Query — returns (list[QueryResult], session_id). Omitting "session" auto-creates
    # a new single-query session; pass the returned session_id back in to continue it.
    results, session_id = us.execute_query("jobs suitable for me", database="alice")
    for r in results:
        print(r.query, "→", r.results)

    # Query — returns (natural language string, session_id)
    answer, session_id = us.execute_query(
        "jobs suitable for me",
        database="alice",
        optional_properties={"output_form": "nl", "session": session_id},
    )
    print(answer)

asyncio.run(main())
```

Set `OPENAI_API_KEY` before running:

```bash
export OPENAI_API_KEY=sk-...
```

## API

### `UserSource(name, properties)`

Constructs a multi-user source. `name` identifies this source in the outer DataRegistry.

| property | Type | Description |
|---|---|---|
| `registry` | `dict` | JSONSource config for the outer DataRegistry's backing store (see source properties below) |
| `schema` | `str` | Default path to `schema.json` (optional); stored as a source property and used when creating or resetting databases |
| `metadata_schema` | `str` | Default path to `metadata_schema.json` (optional) |
| `contact_schema` | `str` | Default path to `contact_schema.json` (optional) |

### Database management

| Method | Description |
|---|---|
| `create_user(name, registry_props, kb_source_props, metadata_source_props, contact_source_props, session_source_props, doc_source_props=None)` *(async)* | Build registry + all built-in sources from scratch and seed schema. `doc_source_props` is optional — defaults to a dummy-embedding, in-memory vector backend (see [Sessions](#sessions)) |
| `list_users()` | Return list of database names |
| `get_user(name)` | Return the database properties dict (contains `"registry"` key), or `None` |
| `remove_user(name)` | Remove database from the outer registry; backing files unchanged |
| `reset_user(name)` *(async)* | Wipe KB data + imported registry entries, then reseed schema |
| `delete_user(name)` *(async)* | Destroy all backing files and remove from the outer registry |

**Source properties format** — all source configs use `_class` + `connection`:

```python
# In-memory JSON (registry, metadata, contacts)
{
    "_class": "blue_data.source.json.memory_json_source.MemoryJSONSource",
    "connection": {"protocol": "json/memory"},
}

# File-backed JSON (registry, metadata, contacts)
{
    "_class": "blue_data.source.json.file_json_source.FileJSONSource",
    "connection": {"protocol": "json/file", "path": "~/.blue-userdb/registries/alice.json"},
}

# In-memory KB
{
    "_class": "blue_data_kb_source.memory_kb_source.MemoryKBSource",
    "connection": {"protocol": "kb/memory"},
}

# File-backed KB (default for CLI)
{
    "_class": "blue_data_kb_source.file_kb_source.FileKBSource",
    "connection": {"protocol": "kb/file", "directory": "~/.blue-userdb/sources/alice"},
}

# Neo4j KB
{
    "_class": "blue_data_kb_source.neo4j.neo4j_kb_source.NEO4JKBSource",
    "connection": {
        "protocol": "kb/neo4j",
        "host": "localhost",
        "port": 7687,
        "user": "neo4j",
        "password": "...",
    },
}
```

### Source management

| Method | Description |
|---|---|
| `add_source(source, database, optional_properties)` *(async)* | Register a source in the KB and optionally extract content |
| `remove_source(database, source_name)` | Remove a source from the DataRegistry (KG data preserved) |

`add_source` accepts:

| optional_property | Type | Description |
|---|---|---|
| `queries` | `list[str]` | Extraction queries — each drives one `import_text` call (Type 2) |
| `name` | `str` | Human-readable label for the source |
| `description` | `str` | Optional description |
| `original` | `str` | Original publication date or provenance note |

### Query

| Method | Description |
|---|---|
| `execute_query(query, database, optional_properties)` | Execute a natural language query; returns `(list[QueryResult], session_id)` or `(str, session_id)` |
| `execute_query_nl(query, database, optional_properties)` | Alias — same behaviour |

`execute_query` contextualises and expands the query via LLM, then retrieves data for each expanded sub-question from the KB *and* the `session_content`/`external_documents` document sources (top-`k` `DOCUMENT.SEARCH` chunks, each tagged `"source"`), assesses completeness, freshness, and privacy across the combined results, and prompts the user for clarification when quality checks fail. Interaction responses are stored back into the KB *and* recorded in the session (see [Sessions](#sessions)).

| optional_property | Type | Description |
|---|---|---|
| `session` | `str` | Session ID to append this query to (reused). Raises `QueryError` if unknown or already ended. Omit to auto-create a new single-query session — **reuse-or-create** |
| `output_form` | `"json"` \| `"nl"` | `"json"` returns `list[QueryResult]`; `"nl"` returns a synthesized natural language string |
| `include_expanded` | `bool` | When `True` (default `False`), also returns the per-sub-question queries and raw results alongside the synthesized answer; the return shape becomes `{"result": ..., "expanded": ...}` |
| `max_interaction_rounds` | `int` | Max clarification rounds when quality metrics fail (default: 3); stops early once all metrics pass |
| `top_k` | `int` | Max KB results per sub-query (default: 10) |

### Data access

| Method | Description |
|---|---|
| `list_data(database)` *(async)* | Raw data entries from the KB (`list[dict]`) |
| `describe_data(database)` *(async)* | Natural language summary of KB data (`str`) |
| `list_sources(database, source_id=None)` *(async)* | KB SOURCE nodes (`list[dict]`), optionally filtered by ID |
| `describe_sources(database, source_id=None)` *(async)* | Natural language summary of sources (`str`) |
| `list_metadata(database)` | User metadata dict from the metadata source |
| `get_metadata(database, key)` | Single metadata value |
| `set_metadata(database, key, value)` | Set a metadata value |
| `delete_metadata(database, key)` | Delete a metadata value |

### Contact methods

Each user stores preferred contact channels in their contacts source. The agent picks the lowest-preference entry when it needs to ask a question.

```python
# Add a contact method
await us.add_contact_method("alice", "email", "work", {
    "address": "alice@example.com",
    "from_address": "agent@blue-userdb.example.com",
    "smtp_host": "smtp.example.com",
    "reply_domain": "blue-userdb.example.com",
    "response_base_url": "http://localhost:8000",
    "inbound_provider": "mailgun",   # mailgun | postmark | sendgrid | smtp_server | stdio
}, preference=1)

# List, get, update, remove
methods = await us.list_contact_methods("alice")
method  = await us.get_contact_method("alice", "email", "work")
await us.update_contact_method("alice", "email", "work", preference=0)
await us.remove_contact_method("alice", "email", "work")
```

#### Supported protocols

| Protocol | Trigger | Notes |
|---|---|---|
| `stdio` | Prompts stdout / reads stdin | Default when no contact methods are registered |
| `email` | Sends SMTP email; awaits inbound reply | Requires `[email]` extra; see detail keys below |
| `webhook` | POSTs JSON to a URL; awaits REST response | Requires `[webhook]` extra |

#### Webhook contact method detail keys

| Key | Required | Default | Description |
|---|---|---|---|
| `url` | yes | — | POST target for outgoing questions |
| `response_base_url` | yes | — | Base URL of `blue-userdb-api` (response_url sent in payload: `{response_base_url}/interactions/{interaction_id}/response`) |
| `headers` | no | _(none)_ | Extra HTTP headers for the outgoing POST |
| `timeout` | no | `300` | Seconds to wait for a response |

```python
await us.add_contact_method("alice", "webhook", "ops", {
    "url": "https://example.com/hook",
    "response_base_url": "http://localhost:8000",
}, preference=2)
```

#### Email contact method detail keys

| Key | Required | Default | Description |
|---|---|---|---|
| `address` | yes | — | Recipient email address |
| `inbound_provider` | no | _(none)_ | How the reply arrives: `mailgun`, `postmark`, `sendgrid`, `smtp_server`, or `stdio` |
| `from_address` | yes¹ | `"agent"` | Sender address shown in From: |
| `smtp_host` | yes¹ | — | SMTP server hostname |
| `smtp_port` | no | `587` | SMTP port |
| `smtp_user` | no | `from_address` | SMTP username |
| `smtp_password` | no | `""` | SMTP password |
| `smtp_use_tls` | no | `True` | Use STARTTLS |
| `reply_domain` | yes¹ | `"localhost"` | Domain for `Reply-To: interaction-{id}@reply_domain` |
| `response_base_url` | yes¹ | — | Base URL of `blue-userdb-api` (link in email body + inbound endpoint) |
| `subject` | no | `"A question for you"` | Email subject line |
| `timeout` | no | `300` | Seconds to wait for a reply |

¹ Not required when `inbound_provider` is `"stdio"`.

**`inbound_provider: "stdio"`** — development / testing mode. Prints a formatted email block to stdout and reads the reply from stdin. No SMTP connection is made and no `blue-userdb-api` is needed.

```python
# Minimal stdio setup — useful in tests and local development
await us.add_contact_method("alice", "email", "dev", {
    "address": "alice@example.com",
    "inbound_provider": "stdio",
})
```

**Inbound webhook providers** (`mailgun`, `postmark`, `sendgrid`) — the provider parses the email reply and POSTs to `POST /interactions/email/inbound?provider=<name>` on `blue-userdb-api`, which resolves the pending Future. Configure your provider's inbound routing to deliver mail sent to `interaction-*@{reply_domain}` to that endpoint.

**`smtp_server`** — reserved for a future `aiosmtpd`-based listener. Currently raises `NotImplementedError`.

### Sessions

A session groups the queries and clarification interactions of one conversation. `execute_query`/`execute_query_nl` use **reuse-or-create** semantics: pass `session` in `optional_properties` to append to an existing session, or omit it to auto-create a new single-query one. Every `execute_query` call returns the `session_id` it landed in.

```python
session_id = await us.create_session("alice")

results, session_id = us.execute_query(
    "jobs suitable for me", database="alice",
    optional_properties={"session": session_id},
)
# further calls with the same session_id continue this session

record = await us.get_session("alice", session_id)
# {"created_at": ..., "ended_at": None, "status": "active",
#  "doc_source_name": "session-<id>",
#  "queries": {"<query_id>": {"query": ..., "interactions": {...}}}}

sessions = await us.list_sessions("alice")   # dict[session_id, record]

await us.end_session("alice", session_id)    # further queries against it raise QueryError
```

| Method | Description |
|---|---|
| `create_session(database)` *(async)* | Create a new session; returns `session_id` |
| `get_session(database, session_id)` *(async)* | Return the session's record (queries + interactions), or `None` |
| `list_sessions(database)` *(async)* | Return `dict[session_id, record]` for all sessions |
| `end_session(database, session_id)` *(async)* | Mark a session `"ended"`; further queries against it raise |

Each clarification interaction — question sent, response received, which contact method handled it — is recorded under its query in the session, and the resolved Q/A pair is also ingested as text into a per-session `DocumentDataSource` (from `blue-data-doc-source`) for later semantic recall. The `interaction_id` recorded here is the same id used internally to correlate an async webhook/email reply (see [Contact methods](#contact-methods) above).

By default, per-session interaction transcripts use a `DummyEmbeddingModel` and an in-memory vector backend — fine for tests, but transcripts won't survive a process restart. Pass `doc_source_props` to `create_user` for a persistent backend:

When `doc_source_props` points the vector backend at `"file"`, each resolved interaction's raw `Q: ...\nA: ...` transcript is also saved as a `.txt` file — named `{query_id}-{interaction_id}.txt` — under `{directory}/transcripts/{session_id}/`, alongside the vector store. With the (default) in-memory backend, nothing is written to disk.

```python
await us.create_user(
    "alice",
    # ...other props...
    session_source_props={...},
    doc_source_props={
        "embedding_model": "dummy",  # or "openai"
        "vector_source": {"backend": "file", "directory": "~/.blue-userdb/sources/alice/sessions"},
    },
)
```

### `QueryResult`

```python
@dataclass
class QueryResult:
    query: str
    results: list[Any]
```

## Schema

The KB schema is defined in `data/schema.txt` (Cypher-like notation) and converted once to `data/schema.json`:

```bash
python tools/convert_schema.py \
    lib/src/blue_data_user_source/data/schema.txt \
    lib/src/blue_data_user_source/data/schema.json
```

The JSON file is consumed by `KBSource.import_database_schema` (entity and relation types) and `KBSource.add_is_subclass_of` (subclass edges).

## CLI

The `blue-userdb` CLI exposes all library operations. See [platform/cli/README.md](../platform/cli/README.md) to install it and [docs/cli.md](../docs/cli.md) for the full command reference (including the `metadata` and `contact` groups omitted from the summary below).

```
blue-userdb [--database NAME] [--data-dir DIR] [--schema-path PATH] COMMAND

database commands:
  blue-userdb database create NAME    Create a new database (auto-selects it)
  blue-userdb database delete NAME    Delete a database and all its data
  blue-userdb database select NAME    Set the active database
  blue-userdb database list           List all databases
  blue-userdb database search KEYWORD Search databases by name
  blue-userdb database reset          Clear KB data and reseed schema
  blue-userdb database config show    Show stored configuration

session commands:
  blue-userdb session start           Create a new session (auto-selects it)
  blue-userdb session select ID       Set the active session
  blue-userdb session end [ID]        End a session (defaults to the selected one)
  blue-userdb session list            List sessions for the active database
  blue-userdb session show [ID]       Show a session's queries and interactions

data commands:
  blue-userdb data query TEXT         Execute a natural language query
  blue-userdb data search QUERY       Search entities and facts
  blue-userdb data list               List all entities and facts
  blue-userdb data import FILE        Import instance data (from blue-userdb data export)
  blue-userdb data export             Export instance data as JSON
  blue-userdb data extract TEXT       Extract entities/facts from free text via LLM
  blue-userdb data source list        List data sources
  blue-userdb data source add FILE    Register a file source (optionally extract)
  blue-userdb data source remove NAME Remove a source from the registry

schema commands:
  blue-userdb schema list             List classes and relations
  blue-userdb schema import FILE      Import a schema
  blue-userdb schema export           Export schema as JSON
  blue-userdb schema search QUERY     Search schema elements
```

Database files are stored under `~/.blue-userdb/` by default.

## Running tests

### Unit tests

Fast, fully offline, no API key required. Covers `UserDataManager`, `UserQueryReasoner`, `ContactManager`, `SessionManager`, `FreshnessMetric`, `CompletenessMetric`, `PrivacyMetric`, and `UserDataPlanner`. `SessionManager` tests exercise a real `DocumentDataSource` (`DummyEmbeddingModel` + in-memory vector backend) — no network calls.

```bash
cd lib
pytest tests/unit/
```

231 tests, ~50 s.

### Benchmarks

Report-only: benchmarks never fail on a metric regression — they print and write scores so drift is visible over time. They are split into three modules:

| Module | Cases | What it measures |
|---|---|---|
| `extraction` | 4 | User-profile text stored via `store_data`, then queried; scores answer coverage |
| `querying` | 5 | Same KB data queried using second-person, "the user", and by-name phrasing; scores result alignment |
| `reasoning` | 22 | Query contextualization precision, expansion coverage, completeness metric, freshness metric, privacy compliance, and interaction question appropriateness per contact channel |

All benchmarks use [VCR cassettes](https://vcrpy.readthedocs.io/en/latest/) for replay. They skip automatically when no cassette exists and `OPENAI_API_KEY` is unset:

```bash
# Run all benchmarks — cases without cassettes skip when OPENAI_API_KEY is unset
cd lib
pytest tests/benchmarks/

# Run a specific module
pytest tests/benchmarks/extraction/
pytest tests/benchmarks/querying/
pytest tests/benchmarks/reasoning/
```

#### Live runs and cassette recording

Each benchmark module ships a `run.py` that runs live against the real OpenAI API, prints a progress line per case, and optionally writes VCR cassettes for later pytest replay:

```bash
export OPENAI_API_KEY=sk-...

# Run all extraction cases with the default model (gpt-4o)
python -m tests.benchmarks.extraction.run

# Run a specific case or model
python -m tests.benchmarks.extraction.run --case basic_profile --model gpt-4o-mini

# Run and record cassettes for pytest replay
python -m tests.benchmarks.extraction.run --record

# Querying benchmark — shows addressing style in progress line
python -m tests.benchmarks.querying.run
python -m tests.benchmarks.querying.run --record

# Reasoning benchmark — all types require OPENAI_API_KEY
python -m tests.benchmarks.reasoning.run                    # all types
python -m tests.benchmarks.reasoning.run --type freshness
python -m tests.benchmarks.reasoning.run --type contextualization --type expansion
python -m tests.benchmarks.reasoning.run --record
```

Common options (all three runners):

| Option | Description |
|---|---|
| `--model MODEL` | Model to use (repeatable; default: `gpt-4o`) |
| `--case CASE_ID` | Run only this case (repeatable; default: all) |
| `--judge-model MODEL` | Model for LLM-judge scoring (default: `gpt-4o-mini`) |
| `--out PATH` | JSON score report path (default: `.reports/live-<timestamp>.json`) |
| `--detail-out PATH` | JSONL detail log path |
| `--record` | Write cassettes to `cassettes/` for pytest replay |

The reasoning runner also accepts `--type` to filter by benchmark type (`contextualization`, `expansion`, `completeness`, `freshness`, `appropriateness`, `privacy`).

Cassettes are saved to `tests/benchmarks/<module>/cassettes/`. Commit them alongside the case files so CI can replay without network access.

#### Benchmark reports

After each run a JSON report and a JSONL detail log are written to `tests/benchmarks/<module>/.reports/` (git-ignored). A Rich table is also printed to the terminal.

## Project structure

```
lib/
├── pyproject.toml
├── src/
│   └── blue_data_user_source/
│       ├── __init__.py
│       ├── source.py              # UserSource — multi-database entry point
│       ├── types.py               # QueryResult, UDbError hierarchy
│       ├── reasoning/
│       │   ├── metric.py          # CompletenessMetric, FreshnessMetric, PrivacyMetric
│       │   └── reasoner.py        # UserQueryReasoner
│       ├── data/
│       │   ├── manager.py         # UserDataManager — source lifecycle + CLS_* constants
│       │   └── planner.py         # UserDataPlanner
│       └── interaction/
│           ├── contact.py         # ContactManager, ContactMethod (stdio, webhook, email)
│           ├── session.py         # SessionManager — sessions, queries, interactions
│           ├── manager.py         # InteractionManager
│           ├── pending.py         # pending_interactions dict (shared Future registry)
│           └── email/
│               ├── adapter.py     # InboundEmailAdapter ABC + provider registry
│               ├── mailgun.py     # Mailgun inbound webhook adapter
│               ├── postmark.py    # Postmark inbound webhook adapter
│               ├── sendgrid.py    # Sendgrid Inbound Parse adapter
│               └── smtp_server.py # Future aiosmtpd-based adapter (NotImplementedError)
└── tests/
    ├── conftest.py                # shared manager fixture (all-memory sources incl. sessions)
    ├── unit/
    │   ├── doubles/
    │   │   └── sources.py         # make_mock_kb helper
    │   ├── data/                  # test_query_executor, test_query_planner, test_source_manager
    │   ├── interaction/           # test_contact_manager, test_session_manager, test_interaction_manager, test_email_adapters
    │   ├── reasoning/             # test_data_assessor, test_query_rewriter
    │   └── sources/               # test_file_source
    └── benchmarks/
        ├── common/                # cases, runner, reasoning_runner, scoring, reporting, capture
        ├── extraction/
        │   ├── cases/*.yaml       # user-profile extraction cases
        │   └── cassettes/         # VCR recordings (committed)
        ├── querying/
        │   ├── cases/*.yaml       # NL query cases (second-person, "the user", by-name)
        │   └── cassettes/
        └── reasoning/
            ├── cases/*.yaml       # contextualization, expansion, completeness,
            │                      # freshness, privacy, appropriateness
            └── cassettes/
```
