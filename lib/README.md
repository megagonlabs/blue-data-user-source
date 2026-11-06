# blue-data-user-source

Python library for UDb — a multi-user knowledge base with natural language querying, LLM-based extraction, and interactive data quality assurance.

Backed by [blue-data](https://github.com/megagonlabs/blue-data), [blue-data-kb-source](https://github.com/megagonlabs/blue-data-kb-source), and [blue-data-doc-source](https://github.com/megagonlabs/blue-data-doc-source) (per-session interaction transcripts, and files registered via `add_source`).

See [docs/](../docs/README.md) for the full documentation set — [guide.md](../docs/guide.md) for a task-oriented walkthrough and [api-reference.md](../docs/api-reference.md) for the complete method-by-method reference. This README covers installation, a quick usage sample, and running this package's tests.

## Requirements

- Python 3.12 or 3.13
- An LLM API key, used by the reasoning and extraction layers: `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` with `BLUE_DATA_LLM_PROVIDER=anthropic`. The calls go through LiteLLM to that provider; see [installation](../docs/installation.md#environment-variables)

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

Use a concrete source: `FileUserSource` keeps the outer DataRegistry (where users are registered as databases and schema paths are stored as source properties) and each user's stores in files, `MemoryUserSource` in memory, and `RedisUserSource` in Redis. A bare `UserSource` has no data directory, so it deletes no files:

```python
import asyncio
from blue_data_user_source import FileUserSource, MemoryUserSource

# File-backed (survives process restarts)
us = FileUserSource("user_source", {
    "connection": {"path": "~/.blue-userdb-lib/registry.json"},
    # "schema": "my_schema.json",   # optional — replaces the bundled schema when creating/resetting databases
})

# In-memory (useful for testing)
us = MemoryUserSource("user_source")
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
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb-lib/registries/alice.json"},
        },
        kb_source_props={
            "_class": "blue_data_kb_source.file_kb_source.FileKBSource",
            "connection": {"protocol": "kb/file", "directory": "~/.blue-userdb-lib/sources/alice"},
        },
        metadata_source_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb-lib/sources/alice/metadata.json"},
        },
        contact_source_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb-lib/sources/alice/contacts.json"},
        },
        session_source_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb-lib/sources/alice/sessions.json"},
        },
        onboard=False,  # the default, True, interviews the user (on the console with console=True)
        # doc_source_props is optional — defaults to OpenAI embeddings searched by
        # vector, in memory, for session transcripts and added files. See "Sessions" below.
    )

    print(us.list_users())       # ["alice"]

    # Reset — clear KB data + imported registry entries, reseed schema
    await us.reset_user("alice")

    # Remove from outer registry AND wipe all backing files
    await us.delete_user("alice")

    # Or remove from outer registry only (KB data kept): after this, delete_user
    # raises UserNotFoundError, so use one or the other
    # us.remove_user("alice")

asyncio.run(main())
```

### Add sources and query

```python
async def main() -> None:
    await us.create_user(
        "alice",
        registry_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb-lib/registries/alice.json"},
        },
        kb_source_props={
            "_class": "blue_data_kb_source.file_kb_source.FileKBSource",
            "connection": {"protocol": "kb/file", "directory": "~/.blue-userdb-lib/sources/alice"},
        },
        metadata_source_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb-lib/sources/alice/metadata.json"},
        },
        contact_source_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb-lib/sources/alice/contacts.json"},
        },
        session_source_props={
            "_class": "blue_data.source.json.file_json_source.FileJSONSource",
            "connection": {"protocol": "json/file", "path": "~/.blue-userdb-lib/sources/alice/sessions.json"},
        },
        onboard=False,  # the default, True, interviews the user (on the console with console=True)
    )

    # Type 1 — register a file (.txt/.pdf/.docx); always parsed, chunked, and
    # embedded into the shared "external_documents" DocumentDataSource
    await us.add_source("data/resume.txt", database="alice")

    # Type 2 — same ingestion, plus extract specific knowledge via LLM into the KG.
    # The file is already a source, so this updates it rather than adding a second.
    await us.add_source(
        "data/resume.txt",
        database="alice",
        optional_properties={"queries": ["What skills does the user have?"]},
    )

    # Remove a source: its document leaves search; facts extracted from it are kept
    await us.remove_source("alice", "data/resume.txt")

    # Query — returns (answer, session_id): the answer is one aggregated table (a list
    # of dicts). Omitting "session" auto-creates a new single-query session; pass the
    # returned session_id back in to continue it.
    answer, session_id = await us.async_execute_query("jobs suitable for me", database="alice")
    print(answer)

    # Query — the answer as prose
    answer, session_id = await us.async_execute_query(
        "jobs suitable for me",
        database="alice",
        optional_properties={"output_form": "nl", "session": session_id},
    )
    print(answer)

asyncio.run(main())
```

Set the provider's key before running (`OPENAI_API_KEY` by default):

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
| `create_user(name, registry_props, kb_source_props, metadata_source_props, contact_source_props, session_source_props, doc_source_props=None)` *(async)* | Build registry + all built-in sources from scratch and seed schema. `doc_source_props` is optional — defaults to OpenAI embeddings searched by vector, in an in-memory vector backend (see [Sessions](#sessions)) |
| `list_users()` | Return list of database names |
| `get_user(name)` | Return the database properties dict (contains `"registry"` key), or `None` |
| `remove_user(name)` | Remove database from the outer registry; backing files unchanged |
| `reset_user(name)` *(async)* | Wipe KB data, ingested documents, metadata, contacts, sessions and imported registry entries, then reseed the schemas. Only files inside the data directory are deleted: a store path recorded outside it, or reached through a symlink out of it, is kept and logged (#156). Returns the paths kept |
| `delete_user(name)` *(async)* | Destroy the user's stored data (backing files, and namespaced stores such as Redis keys) and remove it from the outer registry. Only files inside the data directory are deleted: a store path recorded outside it, or reached through a symlink out of it, is kept and logged (#156). Returns the paths kept |

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
    "connection": {"protocol": "json/file", "path": "~/.blue-userdb-lib/registries/alice.json"},
}

# In-memory KB
{
    "_class": "blue_data_kb_source.memory_kb_source.MemoryKBSource",
    "connection": {"protocol": "kb/memory"},
}

# File-backed KB (default for CLI)
{
    "_class": "blue_data_kb_source.file_kb_source.FileKBSource",
    "connection": {"protocol": "kb/file", "directory": "~/.blue-userdb-lib/sources/alice"},
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
| `remove_source(database, source_name)` *(async)* | Remove a source by name or id: its document leaves search and query answers; facts extracted from it are kept |

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
    "response_base_url": "http://localhost:8003",
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
| `stdio` | Prompts stdout / reads stdin | Default when no contact methods are registered, if the source was given `console=True` (the `console` prop defaults to `False`; the CLI sets it at a terminal) |
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
    "response_base_url": "http://localhost:8003",
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
| `smtp_password` | no | `""` | SMTP password. Without one, the mail is sent without logging in. Masked on reads; may be a `$VAR` reference |
| `smtp_use_tls` | no | `True` | Use STARTTLS |
| `reply_domain` | yes¹ | `"localhost"` | Domain for `Reply-To: interaction-{id}@reply_domain` |
| `response_base_url` | yes¹ | — | Base URL of `blue-userdb-api` (link in email body + inbound endpoint) |
| `subject` | no | `"A question for you"` | Email subject line |
| `timeout` | no | `300` | Seconds to wait for a reply |

¹ Not required when `inbound_provider` is `"stdio"`.

**Secrets.** `smtp_password`, a webhook's `url` and `headers`, and a notification `endpoint` are secret: every read path (REST, MCP tools, `blue-userdb contact list/get`) returns them masked as `***`. To keep `smtp_password`, a webhook's `url` or a header value out of the contacts store too, store a reference to an environment variable instead, e.g. `"smtp_password": "$BLUE_DATA_USER_CONTACT_SMTP_PASSWORD"`; it is resolved when a message is sent, and shown as-is on reads. Only variables named `BLUE_DATA_USER_CONTACT_*` can be referenced: any other name is refused when the contact is written, and fails the clarification when it is used, so a contact cannot read the server's other settings.

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

A session groups the queries and clarification interactions of one conversation. Queries use **reuse-or-create** semantics: pass `session` in `optional_properties` to append to an existing session, or omit it to auto-create a new single-query one. `async_execute_query` returns the `session_id` each query landed in; the `DataSource` forms `execute_query`/`execute_query_nl` return `list[dict]` rows only (blue-data's contract), so with them you create the session first and pass it.

```python
session_id = await us.create_session("alice")

answer, session_id = await us.async_execute_query(
    "jobs suitable for me", database="alice",
    optional_properties={"session": session_id},
)
# further calls with the same session_id continue this session

record = await us.get_session("alice", session_id)
# {"created_at": ..., "ended_at": None, "status": "active",
#  "doc_source_name": "session_content",
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

By default, session transcripts and added files are embedded with OpenAI (`text-embedding-3-small`), searched by vector, and kept in an in-memory vector backend, so they won't survive a process restart. Pass `doc_source_props` to `create_user` for a persistent backend:

When `doc_source_props` points the vector backend at `"file"`, each resolved interaction's raw `Q: ...\nA: ...` transcript is also saved as a `.txt` file — named `{query_id}-{interaction_id}.txt` — under `{directory}/transcripts/{session_id}/`, alongside the vector store. With the (default) in-memory backend, nothing is written to disk.

```python
await us.create_user(
    "alice",
    # ...other props...
    session_source_props={...},
    doc_source_props={
        "embedding_model": "openai",  # or "dummy" (offline; only with "bm25")
        "search_mode": "vector",      # or "hybrid" or "bm25"
        "vector_source": {"backend": "file", "directory": "~/.blue-userdb-lib/sources/alice/sessions"},
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
  blue-userdb database reset          Clear the database and reseed its schema
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
  blue-userdb data source remove NAME Remove a source (extracted facts are kept)

schema commands:
  blue-userdb schema list             List classes and relations
  blue-userdb schema import FILE      Import a schema
  blue-userdb schema export           Export schema as JSON
  blue-userdb schema search QUERY     Search schema elements
```

Database files are stored under `~/.blue-userdb/` by default.

## Running tests

### Unit tests

Fast, fully offline, no API key required. Covers `UserDataManager`, `UserQueryReasoner`, `ContactManager`, `SessionManager`, `FreshnessMetric`, `CompletenessMetric`, `PrivacyMetric`, and `UserDataPlanner`. `SessionManager` tests exercise a real `DocumentDataSource` (`DummyEmbeddingModel` + in-memory vector backend) — no network calls. Tests that create users pass the `dummy` embedding with `bm25` search explicitly, since a new user otherwise embeds with OpenAI.

```bash
cd lib
pytest tests/unit/
```

299 tests, ~5 s. `tests/unit/conftest.py` fails any test that opens a connection or resolves a host outside loopback, so a test that would reach OpenAI fails at once rather than silently spending tokens.

### Benchmarks

Report-only: benchmarks never fail on a metric regression — they print and write scores so drift is visible over time. They are split into three modules:

| Module | Cases | What it measures |
|---|---|---|
| `extraction` | 4 | User-profile text stored via `store_data`, then queried; scores answer coverage |
| `querying` | 5 | Same KB data queried using second-person, "the user", and by-name phrasing; scores result alignment |
| `reasoning` | 22 | Query contextualization precision, expansion coverage, completeness metric, freshness metric, privacy compliance, and interaction question appropriateness per contact channel |

**The regression check is a live run** (below), compared against the committed [baseline](#the-baseline). The pytest wrappers replay [VCR cassettes](https://vcrpy.readthedocs.io/en/latest/) recorded locally with `--record`. Cassettes are not committed, and replay is not yet complete (#150): the judge's calls are not recorded, and the OpenAI client needs a key even to replay. Without cassettes and without `OPENAI_API_KEY`, every case skips:

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
| `--note TEXT` | Note recorded with the run in the module's results history |
| `--no-history` | Do not record the run in the module's results history |
| `--record` | Write cassettes to `cassettes/` for pytest replay |

The reasoning runner also accepts `--type` to filter by benchmark type (`contextualization`, `expansion`, `completeness`, `freshness`, `appropriateness`, `privacy`).

Cassettes are saved to `tests/benchmarks/<module>/cassettes/` and are git-ignored. One full run is about 29 MB, and since VCR matches requests on method and URL only, a replay returns the recorded answers whatever the code now asks: it can catch harness breakage, not a product regression.

Recording drops account identifiers from responses (the OpenAI organization and project ids, and cookies; request `authorization` headers are filtered too). To scrub cassettes recorded some other way: `python -m tests.benchmarks.common.cassettes`.

#### Benchmark reports

After each run a JSON report and a JSONL detail log are written to `tests/benchmarks/<module>/.reports/` (git-ignored). A Rich table is also printed to the terminal.

#### Results history

Each module keeps its committed run history, as blue-data-kb-source does for its extraction benchmark:

| Module | Results page |
|---|---|
| `extraction` | [`tests/benchmarks/extraction/results/`](tests/benchmarks/extraction/results/README.md) |
| `querying` | [`tests/benchmarks/querying/results/`](tests/benchmarks/querying/results/README.md) |
| `reasoning` | [`tests/benchmarks/reasoning/results/`](tests/benchmarks/reasoning/results/README.md) |

Every full live run of a module (no `--case`, and for reasoning no `--type`) appends one summary line to its `results/history.jsonl` — commit, models, the value per case and its mean per group (reasoning type, querying addressing style), tokens, latency and the `--note` — and regenerates `results/README.md` from it: the latest run with the change since the previous one and a sparkline per row, Mermaid charts of the trend over runs and of the latest run per group, and tables per case and of all runs. Commit both files to keep the run; pass `--no-history` for a run that should not be kept.

The value of a case is its hit rate (extraction, querying) or judged score (contextualization, expansion, appropriateness). A metric case (completeness, freshness, privacy) declares `expect_pass` — whether the metric should pass its threshold for that input — and counts 1.0 when the metric's pass/fail decision matches and 0.0 when it does not; its raw score is not "higher is better" (an empty result set *should* score 0 on completeness).

```bash
# Record a past run from its report, or re-render the pages
python -m tests.benchmarks.common.history add tests/benchmarks/querying/.reports/live-<stamp>.json --module querying --note "..."
python -m tests.benchmarks.common.history render
```

A run whose full score reports are worth keeping beside its summary is committed as a snapshot under `tests/benchmarks/results/<date>-<model>/` — each module's score report (written with `--out tests/benchmarks/results/<run>/<module>.json`) and a `run.json` (model, judge model, date, commit, commands) — and its history lines link to it. `python -m tests.benchmarks.common.history add tests/benchmarks/results/<run>/` records a snapshot that is not in the history yet.

#### The baseline

One run in each module's history is flagged as its baseline (now the first, 2026-10-10 gpt-4o run). A case scoring more than 0.15 below its value in the baseline run is a regression: the pytest replay emits a `BenchmarkRegression` warning, and the live runners print it. Neither fails the run: LLM-judged scores are noisy, and the benchmarks stay report-only. Cases run on a different model than the baseline's, and new cases, are not compared.

To make another run the baseline (default: the module's latest run):

```bash
python -m tests.benchmarks.common.history baseline --module querying [--run <run_id>]
```

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
        │   └── cassettes/         # VCR recordings (local, git-ignored)
        ├── querying/
        │   ├── cases/*.yaml       # NL query cases (second-person, "the user", by-name)
        │   └── cassettes/
        └── reasoning/
            ├── cases/*.yaml       # contextualization, expansion, completeness,
            │                      # freshness, privacy, appropriateness
            └── cassettes/
```
