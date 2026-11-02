# Developer Guide

This is a task-oriented walkthrough of the Python library. For the full method-by-method reference, see [api-reference.md](api-reference.md). For the CLI equivalent of everything here, see [cli.md](cli.md).

## Setup

`UserSource` is abstract over how the outer user registry is stored — pick a ready-made backend (see [architecture.md](architecture.md#backends)): `MemoryUserSource`, `FileUserSource`, or `RedisUserSource`.

> Most write operations are `async def`. Call them from inside an `async` function and run with `asyncio.run(...)`. `execute_query`/`execute_query_nl` are synchronous convenience wrappers (`async_execute_query` is the `async` form).

```python
import asyncio
from blue_data_user_source import FileUserSource

async def main():
    us = FileUserSource("us", {"connection": {"path": "~/.blue-userdb-lib/registry.json"}})
    ...

asyncio.run(main())
```

A leading `~` in the registry path, and in any store path or directory passed to `create_user`, is expanded to your home directory. Give the library a directory of its own: the CLI, MCP and REST servers keep their users under `~/.blue-userdb`, and a user of the same name whose stores point at the same files shares them, so deleting either one deletes both. `delete_user` and `reset_user` remove only files under the registry file's directory; a store path outside it is kept and returned.

---

## Creating a user

Each user gets its own `DataRegistry` — a knowledge graph, and three JSON stores (metadata, contacts, sessions) — built from scratch with `create_user`. All five source-property arguments are required; `doc_source_props` is optional: it sets up the stores for session transcripts and added files, and defaults to OpenAI embeddings (`text-embedding-3-small`) searched by vector, in an in-memory vector store. See [Document search](#document-search).

```python
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
    onboard=False,   # the default, True, interviews the user (on the console with console=True)
)

print(us.list_users())          # ["alice"]
await us.reset_user("alice")    # clear KB data, documents, metadata, contacts, sessions; reseed
# Then one of:
us.remove_user("alice")         # remove from outer registry only — backing files kept
# await us.delete_user("alice") # or: remove from outer registry AND wipe all backing files
```

For an in-memory KB during development, swap `kb_source_props` for `blue_data_kb_source.memory_kb_source.MemoryKBSource`; for Neo4j, `blue_data_kb_source.neo4j.neo4j_kb_source.NEO4JKBSource`.

### Document search

Session transcripts and added files go into document stores, and each query searches them alongside the KB. How they are searched is chosen when the user is created and recorded with the user (`get_user(name)["doc_source"]`):

| `search_mode` | Finds | Needs |
|---|---|---|
| `vector` (default) | passages close in meaning to the question | a real embedding: `openai` (`text-embedding-3-small`), so `OPENAI_API_KEY`, and embedding calls when documents are added and on each search |
| `hybrid` | keyword and meaning matches, fused | the same as `vector` |
| `bm25` | passages sharing the question's words | no embedding calls, but its index lives only in the process that ingested the documents: after a restart (every CLI command) it finds nothing, and `hybrid` falls back to `vector` |

```python
us.create_database("alice", {"doc_search_mode": "hybrid"})                              # OpenAI embeddings
us.create_database("bob", {"doc_embedding_model": "dummy", "doc_search_mode": "bm25"})  # offline, one process
```

`doc_embedding_model` is `openai` (the default) or `dummy`, a hash with no notion of meaning: `vector` or `hybrid` over `dummy` raises `QueryError`. With `create_user`, put the same choices in `doc_source_props` as `embedding_model` and `search_mode`. Users created before 1.0 record no mode: one with the `dummy` embedding is searched with `bm25`. Changing a user's embedding means re-embedding its documents, so recreate the user instead.

---

## Adding data sources

Registering a file always ingests it into a shared `external_documents` document store (parsed, chunked, embedded) — that's Type 1. Passing `queries` also runs an LLM extraction agent that writes structured attributes into the knowledge graph — Type 2.

```python
# Type 1 — register + ingest for later search
await us.add_source("data/resume.txt", database="alice")

# Type 2 — also extract specific attributes via LLM into the KG
await us.add_source(
    "data/resume.txt", database="alice",
    optional_properties={"queries": ["What skills does the user have?"]},
)

await us.remove_source("alice", "data/resume.txt")   # document leaves search; extracted facts kept
```

Adding a file that is already a source, as the Type 2 step does here, updates that source instead of adding a second one: its chunks are replaced by the new ingest (so an edited file is picked up), and the extraction is recorded under it. The same file under another `name` is another source.

---

## Querying in natural language

`execute_query` rewrites the query, expands it into sub-questions, retrieves data for each, and assesses the combined result — asking for clarification via a contact method when quality checks fail. Requires the LLM provider's key for the rewriting/expansion/assessment prompts (`OPENAI_API_KEY` by default; see [installation](installation.md#environment-variables)).

```python
answer, session_id = await us.async_execute_query("jobs suitable for me", database="alice")
print(answer)          # one aggregated table: a list of dicts

answer, session_id = await us.async_execute_query(
    "jobs suitable for me", database="alice",
    optional_properties={"output_form": "nl", "session": session_id},
)
print(answer)          # prose

# The DataSource form (blue-data's contract) returns rows only, with no session id:
rows = us.execute_query("jobs suitable for me", database="alice")   # the table; "nl" gives [{"answer": ...}]
```

`optional_properties`:

| Key | Type | Description |
|---|---|---|
| `session` | `str` | Session to append this query to (reused). Omit to auto-create a new single-query session |
| `output_form` | `"json"` \| `"nl"` | `"json"` (default) returns one aggregated table (a list of dicts); `"nl"` returns prose |
| `include_expanded` | `bool` | Also return the per-sub-question queries/results alongside the synthesized answer |
| `max_interaction_rounds` | `int` | Max clarification rounds when quality metrics fail (default 3) |
| `max_subqueries` | `int` | Most sub-questions added to the query, each answered by the KB's agent; `0` answers the query alone (default: as many as the expansion proposes, at most 5). See [Cost](#cost) |
| `max_kb_turns` | `int` | Most tool-calling turns of the KB's agent per sub-question (default 25); out of turns, it makes one more call to answer with what it found |
| `model` | `str` | Model for the reasoning steps and the KB's agent, of the `BLUE_DATA_LLM_PROVIDER` provider (default: `BLUE_DATA_USER_SOURCE_REASONING_LLM_MODEL`, `BLUE_DATA_USER_SOURCE_LLM_MODEL` or `BLUE_DATA_LLM_MODEL`, else the provider's default: gpt-4o for openai, claude-opus-4-8 for anthropic) |
| `on_interaction_start`, `on_interaction_end` | `Callable[[], None]` | Called just before a clarification question is put to the user and once the exchange is over, answered or not; a CLI pauses its live status display in between |
| `top_k` | `int` | Max chunks taken from each document store per sub-question (default 5) |

`async_execute_query` is the library's own query call and returns `(answer, session_id)`. `execute_query` and `execute_query_nl` are the `DataSource` forms: blue-data's contract has them return `list[dict]` rows, so the answer comes back as rows (the table, or one `{"answer": ...}` row for `"nl"`) and the session id does not. To use a session through them, create it first and pass it as `session`.

---

### Cost

A query is a pipeline of LLM calls: it rewrites the question, expands it into up to 5 sub-questions, answers each sub-question (and the rewritten question) with the KB's tool-calling agent, scores the result, and writes the answer. The KB's agent makes most of the calls. Extraction (`add_source` with `queries`, `data source add --query`) is a similar agent loop, run `effort` times over the text.

Measured with gpt-4o at list prices ($2.50 per million input tokens, $10 per million output), clarification rounds off:

| Run | Calls | Input tokens | Cost |
|---|---|---|---|
| Extract one sentence (`effort` medium) | 27–33 | 68K–84K | $0.19–$0.24 |
| One query over it, defaults | 42–67 | 70K–145K | $0.19–$0.38 |
| The same query, `max_subqueries=1, max_kb_turns=8` | 16 | 20K | $0.06 |
| The same query, `max_subqueries=0, max_kb_turns=6` | 10 | 9K | $0.03 |
| A query over the quickstart's résumé, defaults | 55–95 | 213K–824K | $0.57–$2.11 |

In that small test, all four queries gave the same answer. To spend less:

- **Bound the query:** `max_subqueries`, `max_kb_turns` and `max_interaction_rounds` (CLI `--max-subqueries`, `--max-kb-turns`, `--max-rounds`; the same names on MCP `query` and REST `POST /{name}/query`). Each clarification round adds a scoring pass and a question to the user.
- **Use a cheaper model:** `model` on a query, or `optional_properties["model"]` on `add_source`. In the CLI, `BLUE_DATA_USER_SOURCE_LLM_MODEL` (or the per-function `…_REASONING_LLM_MODEL` and `…_EXTRACTION_LLM_MODEL`) in the profile, or `--model`. The KB's agent uses it too.
- **Extract with fewer passes:** `effort="low"` (`--effort low`) is one pass instead of two.
- Document embeddings (`text-embedding-3-small`) cost a small fraction of the above.

## Sessions

A session groups the queries and clarification interactions of one conversation. Queries use reuse-or-create semantics: pass a `session` id to continue one, omit it to auto-create a single-query session. `async_execute_query` returns the `session_id` each query landed in.

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

Each clarification interaction (question, response, contact method used) is recorded under its query in the session record, and the resolved Q/A pair is also ingested as text into the session's document store for later semantic recall. See [10-data-model.md](../design/10-data-model.md) §6 for the full record schema.

---

## Contact methods

Contact methods are stored per user and consulted whenever the reasoning layer needs to ask for clarification.

```python
await us.add_contact_method("alice", "email", "work", {
    "address": "alice@example.com",
    "from_address": "agent@blue-userdb.example.com",
    "smtp_host": "smtp.example.com",
    "reply_domain": "blue-userdb.example.com",
    "response_base_url": "http://localhost:8003",
    "inbound_provider": "mailgun",   # mailgun | postmark | sendgrid | smtp_server | stdio
}, preference=1)

methods = await us.list_contact_methods("alice")
method  = await us.get_contact_method("alice", "email", "work")
await us.update_contact_method("alice", "email", "work", preference=0)
await us.remove_contact_method("alice", "email", "work")
```

Supported protocols: `stdio` (default when nothing is registered and the source was given `console=True` — never on the REST or MCP servers), `email` (requires the `email` extra), `webhook` (requires the `webhook` extra) — plus schema-only entries (`sms`, `messaging`, `enterprise`, `notification`, `session`) that can be recorded via the CLI/MCP but have no transport in this release, so they are never used to contact the user — contact selection skips them. `inbound_provider: "stdio"` on `email` is a development mode: prints the outgoing message to stdout and reads the reply from stdin, no SMTP or REST API needed. See [api-reference.md](api-reference.md#contactmanager--contactmethod) for every detail key.

With more than one method registered, `ContactManager.identify_contact_method` asks an LLM to choose, weighing each method's `preference`, whether it's asynchronous, the user's `availability.*` settings (localized to `identity.timezone`), and whether they're `out_of_office`.

---

## Metadata

A schema-described, dot-path-addressable store — `identity`, `preferences`, `availability`, `privacy` — consulted by the reasoning and interaction layers.

```python
us.set_metadata("alice", "identity.name", "Alice Smith")
us.set_metadata("alice", "identity.timezone", "America/New_York")
us.set_metadata("alice", "availability.working_hours", "09:00-17:00 Mon-Fri")
us.set_metadata("alice", "privacy.consent_level", "standard")

print(us.get_metadata("alice", "identity.name"))
print(us.list_metadata("alice"))
us.delete_metadata("alice", "identity.pronouns")
```

See [data/metadata_schema.json](../lib/src/blue_data_user_source/data/metadata_schema.json) for every field and its description.

---

## Benchmarks

`lib/tests/benchmarks/` scores query rewriting/expansion, extraction, and end-to-end querying against gold-standard cases, run live against the real API and recorded in a committed history per module (`lib/tests/benchmarks/<module>/results/`, with trend charts) and compared with a baseline run flagged in it. Report-only — a regression is reported, never fails the build. See [`lib/README.md`](../lib/README.md#benchmarks) for the full scoring methodology and how to run a live pass.

```bash
cd lib
pytest tests/benchmarks/
python -m tests.benchmarks.reasoning.run --record
```

---

## Next steps

- [api-reference.md](api-reference.md) — every method, parameter, and result type
- [extending.md](extending.md) — implementing a new registry/KB backend or contact method protocol
- [cli.md](cli.md) / [mcp.md](mcp.md) / [api.md](api.md) — the same operations from the command line, an LLM agent, or HTTP
