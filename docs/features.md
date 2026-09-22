# Features

## Multi-user knowledge store

Each user gets an isolated `DataRegistry` — its own knowledge graph, metadata, contacts, and session records — addressed by name. `UserSource` manages the outer registry of users.

```python
await us.create_user("alice", registry_props=..., kb_source_props=..., metadata_source_props=...,
                      contact_source_props=..., session_source_props=...)

print(us.list_users())        # ["alice"]
await us.reset_user("alice")  # clear KB data + imported sources, reseed schema
await us.delete_user("alice") # remove from registry and wipe all backing files
```

Three ready-made `UserSource` backends select where the *outer* registry (the list of users) lives: `MemoryUserSource` (in-process, non-persistent), `FileUserSource` (JSON file, the CLI/MCP/API default), and `RedisUserSource` (Redis JSON). Each user's own per-user registry is configured independently at `create_user` time — see [architecture.md](architecture.md#backends).

---

## Data ingestion from files

Registering a file always parses, chunks, and embeds it into a shared `external_documents` store so it can be searched or contribute to later query results — that's Type 1. Adding `queries` also runs an LLM extraction agent that writes specific attributes into the knowledge graph — Type 2.

```python
# Type 1 — register + ingest for later search
await us.add_source("resume.txt", database="alice")

# Type 2 — also extract structured attributes into the KG
await us.add_source(
    "resume.txt", database="alice",
    optional_properties={"queries": ["What skills does the user have?"]},
)
```

---

## Natural language querying with quality-gated interaction

`execute_query` runs a multi-step reasoning pipeline rather than a single lookup: it rewrites the query (resolving self-references like "me"/"you" to the user's actual name), expands it into schema-grounded sub-questions, retrieves data for each from the knowledge graph *and* any registered documents, and assesses the combined result against quality metrics — prompting the user for clarification when checks fail.

```python
results, session_id = us.execute_query("jobs suitable for me", database="alice")
for r in results:
    print(r.query, "→", r.results)

answer, session_id = us.execute_query(
    "jobs suitable for me", database="alice",
    optional_properties={"output_form": "nl"},
)
```

Two quality metrics run by default — `CompletenessMetric` and `FreshnessMetric` — plus `PrivacyMetric` whenever a data manager is available, whose pass threshold moves with the user's `privacy.consent_level` (stricter at `minimal`, looser at `full`). See [architecture.md](architecture.md#reasoning-layer) for the full assess-interact-reassess loop.

---

## Sessions

A session groups the queries and clarification interactions of one conversation, so later queries have context from earlier ones and every interaction is recorded durably. `execute_query` uses reuse-or-create semantics: pass a `session` id to continue one, or omit it to auto-create a single-query session.

```python
session_id = await us.create_session("alice")

results, session_id = us.execute_query(
    "jobs suitable for me", database="alice",
    optional_properties={"session": session_id},
)

record = await us.get_session("alice", session_id)
sessions = await us.list_sessions("alice")
await us.end_session("alice", session_id)
```

Resolved clarification Q/A pairs are also ingested as text into a per-session document store for later semantic recall.

---

## Multi-channel interaction

Configurable contact methods let the reasoning layer ask the user directly when it needs more information. `stdio` prints to the terminal by default; `email` and `webhook` are available as extras, with an availability-aware channel picker.

```python
await us.add_contact_method("alice", "email", "work", {
    "address": "alice@example.com",
    "from_address": "agent@blue-userdb.example.com",
    "smtp_host": "smtp.example.com",
    "reply_domain": "blue-userdb.example.com",
    "response_base_url": "http://localhost:8000",
    "inbound_provider": "mailgun",
}, preference=1)
```

With more than one method registered, an LLM picks the best channel for the moment — weighing each method's stated preference, whether it's asynchronous, the user's `preferred_channel`/`working_hours` (localized to `identity.timezone`), and whether the user is currently `out_of_office`. `availability.by_topic.<topic>` lets different projects override these settings independently. See [architecture.md](architecture.md#interaction-layer).

---

## User metadata

A schema-described, dot-path-addressable metadata store — `identity`, `preferences`, `availability`, and `privacy` categories — read by the reasoning and interaction layers to personalize queries, phrasing, and channel selection.

```python
us.set_metadata("alice", "identity.name", "Alice Smith")
us.set_metadata("alice", "identity.timezone", "America/New_York")
us.set_metadata("alice", "privacy.consent_level", "standard")

print(us.get_metadata("alice", "identity.name"))   # "Alice Smith"
print(us.list_metadata("alice"))                    # full nested dict
```

---

## CLI

A full command-line interface (`blue-userdb`) over the library — databases, sessions, data, schema, metadata, and contacts.

```bash
blue-userdb database create alice
blue-userdb data source add resume.txt --query "What skills does the user have?"
blue-userdb data query "What jobs are suitable for me?"
```

See [cli.md](cli.md) for the full command reference.

---

## MCP server

Exposes the same operations as MCP tools, so Claude and other MCP clients can create users, ingest sources, query, and manage metadata/contacts directly in an agentic session.

```bash
blue-userdb-mcp
```

```json
{
  "mcpServers": {
    "blue-data-user": { "command": "blue-userdb-mcp" }
  }
}
```

See [mcp.md](mcp.md) for the full tool reference and Claude Desktop configuration.

---

## REST API

An HTTP interface (FastAPI) exposing databases, queries, sessions, sources, metadata, and contacts — plus interaction endpoints so webhook, form-based, and inbound-email replies can resolve a pending clarification.

```bash
blue-userdb-api
curl -X POST http://localhost:8000/alice/query -d '{"query": "What skills does alice have?"}'
```

See [api.md](api.md) for the full endpoint reference.
