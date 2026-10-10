# Developer Guide

This is a task-oriented walkthrough of the Python library. For the full method-by-method reference, see [api-reference.md](api-reference.md). For the CLI equivalent of everything here, see [cli.md](cli.md).

## Setup

`UserSource` is abstract over how the outer user registry is stored — pick a ready-made backend (see [architecture.md](architecture.md#backends)): `MemoryUserSource`, `FileUserSource`, or `RedisUserSource`.

> Most write operations are `async def`. Call them from inside an `async` function and run with `asyncio.run(...)`. `execute_query`/`execute_query_nl` are synchronous convenience wrappers (`async_execute_query` is the `async` form).

```python
import asyncio
from blue_data_user_source import FileUserSource

async def main():
    us = FileUserSource("us", {"connection": {"path": "~/.blue-userdb/registry.json"}})
    ...

asyncio.run(main())
```

---

## Creating a user

Each user gets its own `DataRegistry` — a knowledge graph, and three JSON stores (metadata, contacts, sessions) — built from scratch with `create_user`. All five source-property arguments are required; `doc_source_props` is optional (defaults to a `DummyEmbeddingModel` + in-memory vector store for per-session/per-file document ingestion).

```python
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

print(us.list_users())          # ["alice"]
await us.reset_user("alice")    # clear KB data, documents, metadata, contacts, sessions; reseed
us.remove_user("alice")         # remove from outer registry only — backing files kept
await us.delete_user("alice")   # remove from outer registry AND wipe all backing files
```

For an in-memory KB during development, swap `kb_source_props` for `blue_data_kb_source.memory_kb_source.MemoryKBSource`; for Neo4j, `blue_data_kb_source.neo4j.neo4j_kb_source.NEO4JKBSource`.

---

## Adding data sources

Registering a file always ingests it into a shared `external_documents` document store (parsed, chunked, embedded) — that's Type 1. Passing `queries` also runs an LLM extraction agent that writes structured attributes into the knowledge graph — Type 2.

```python
# Type 1 — register + ingest for later search
await us.add_source("resume.txt", database="alice")

# Type 2 — also extract specific attributes via LLM into the KG
await us.add_source(
    "resume.txt", database="alice",
    optional_properties={"queries": ["What skills does the user have?"]},
)

await us.remove_source("alice", "resume.txt")   # document leaves search; extracted facts kept
```

---

## Querying in natural language

`execute_query` rewrites the query, expands it into sub-questions, retrieves data for each, and assesses the combined result — asking for clarification via a contact method when quality checks fail. Requires `OPENAI_API_KEY` for the rewriting/expansion/assessment prompts.

```python
results, session_id = us.execute_query("jobs suitable for me", database="alice")
for r in results:
    print(r.query, "→", r.results)

answer, session_id = us.execute_query(
    "jobs suitable for me", database="alice",
    optional_properties={"output_form": "nl", "session": session_id},
)
print(answer)
```

`optional_properties`:

| Key | Type | Description |
|---|---|---|
| `session` | `str` | Session to append this query to (reused). Omit to auto-create a new single-query session |
| `output_form` | `"json"` \| `"nl"` | `"json"` (default) returns `list[QueryResult]`; `"nl"` returns a synthesized string |
| `include_expanded` | `bool` | Also return the per-sub-question queries/results alongside the synthesized answer |
| `max_interaction_rounds` | `int` | Max clarification rounds when quality metrics fail (default 3) |
| `top_k` | `int` | Max KB results per sub-question (default 10) |

`execute_query_nl` is an alias with identical behavior.

---

## Sessions

A session groups the queries and clarification interactions of one conversation. `execute_query` uses reuse-or-create semantics: pass a `session` id to continue one, omit it to auto-create a single-query session — every call returns the `session_id` it landed in.

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
    "response_base_url": "http://localhost:8000",
    "inbound_provider": "mailgun",   # mailgun | postmark | sendgrid | smtp_server | stdio
}, preference=1)

methods = await us.list_contact_methods("alice")
method  = await us.get_contact_method("alice", "email", "work")
await us.update_contact_method("alice", "email", "work", preference=0)
await us.remove_contact_method("alice", "email", "work")
```

Supported protocols: `stdio` (default when nothing is registered and the process has a console — never on the REST or MCP servers), `email` (requires the `email` extra), `webhook` (requires the `webhook` extra) — plus schema-only entries (`sms`, `messaging`, `enterprise`, `notification`, `session`) that can be recorded via the CLI/MCP but have no transport in this release, so they are never used to contact the user — contact selection skips them. `inbound_provider: "stdio"` on `email` is a development mode: prints the outgoing message to stdout and reads the reply from stdin, no SMTP or REST API needed. See [api-reference.md](api-reference.md#contactmanager--contactmethod) for every detail key.

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

`lib/tests/benchmarks/` scores query rewriting/expansion, extraction, and end-to-end querying against gold-standard cases, run live against the real API and compared with a committed baseline (`lib/tests/benchmarks/baseline.json`, from the versioned runs under `results/`). Report-only — a regression is reported, never fails the build. See [`lib/README.md`](../lib/README.md#benchmarks) for the full scoring methodology and how to run a live pass.

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
