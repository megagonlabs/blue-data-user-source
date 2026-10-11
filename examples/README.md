# blue-data-user-source Examples

This directory contains runnable examples organized by purpose, mirroring the sibling
[`blue-data-kb-source/examples/`](https://github.com/megagon-internal/blue-data-kb-source/tree/1.0/examples) layout.

Every script below was actually run against a real OpenAI-backed environment during
authoring, with its stdout captured verbatim into the matching `.output.txt` — none of
the sample output is hand-written.

## Quick start

```bash
cd lib && pip install -e .
export OPENAI_API_KEY=sk-...
python3 examples/backends/memory_quickstart.py
```

See [docs/installation.md](../docs/installation.md) for the full setup (all four
packages, env vars, sibling-repo dependencies).

---

## backends/ — UserSource storage backends

Start here when integrating `blue-data-user-source` into a new application.
`UserSource` has a single backend axis — **where a user's registry, metadata, contacts,
and sessions are stored** — unlike `blue-data-kb-source`, which also varies its search
index; `UserSource` has no analogous search/vector-backend axis, so there's no
`keyword_search_demo.py`/`semantic_search_demo.py`/`chromadb_...` equivalent here.

### Minimal in-memory quickstart (`memory_quickstart.py`)

~45 lines: create a user, extract a fact from one file via `add_source`, ask a question
about it. No persistence.

```bash
python3 examples/backends/memory_quickstart.py
```

**Requires:** `OPENAI_API_KEY` (the reasoning/query pipeline always calls the LLM, even
for an in-memory demo — there's no LLM-free path through `execute_query`) |
**[Sample output](backends/memory_quickstart.output.txt)**

### FileUserSource full pipeline (`file_backend_demo.py`)

Every major operation against the file-backed `UserSource`: create a user (registry,
KB, metadata, contacts, sessions all as JSON files on disk; metadata auto-seeded from
`data/metadata_schema.json`), a session with a query, `add_source` extraction, then
persistence across a simulated restart — a second `FileUserSource` instance pointed at
the same directory, with no explicit save step.

```bash
python3 examples/backends/file_backend_demo.py
```

**Requires:** `OPENAI_API_KEY` | **[Sample output](backends/file_backend_demo.output.txt)**

### RedisUserSource (`redis_backend_demo.py`)

Same shape as the file demo, Redis-backed. `blue-data-kb-source` ships no Redis KB
backend, so the knowledge graph here stays memory-backed — only the registry, metadata,
contacts, and sessions layers are Redis-backed. Runs against Redis logical database 15
(isolated from whatever else lives on the shared instance's default database) and
flushes only that database when done, so it's safe against a shared Redis.

```bash
redis-stack-server &   # or: docker run -p 6379:6379 redis/redis-stack
python3 examples/backends/redis_backend_demo.py
```

**Requires:** `OPENAI_API_KEY`, Redis on `localhost:6379` |
**[Sample output](backends/redis_backend_demo.output.txt)**

> **Freshness and the user's reply.** `FreshnessMetric` (evaluated alongside
> `CompletenessMetric`) scores the timestamps of the evidence. The user's reply joins the
> evidence with a fresh timestamp, so a confirmation or correction can make the answer
> current (#125). Retrieved evidence that carries no `modified`/`created` timestamp at all
> still scores `0.0` on its own, which can cost clarification rounds when nothing else is
> stale (#98).

---

## Summary table

| File | Folder | API key | External | Output |
|---|---|---|---|---|
| `memory_quickstart.py` | backends | OpenAI | — | [output](backends/memory_quickstart.output.txt) |
| `file_backend_demo.py` | backends | OpenAI | — | [output](backends/file_backend_demo.output.txt) |
| `redis_backend_demo.py` | backends | OpenAI | Redis | [output](backends/redis_backend_demo.output.txt) |
| `query_rewrite_demo.py` | feature-demos | OpenAI | — | [output](feature-demos/query_rewrite_demo.output.txt) |
| `output_formats_demo.py` | feature-demos | OpenAI | — | [output](feature-demos/output_formats_demo.output.txt) |
| `metadata_demo.py` | feature-demos | none | — | [output](feature-demos/metadata_demo.output.txt) |
| `contact_resolution_demo.py` | feature-demos | OpenAI | — | [output](feature-demos/contact_resolution_demo.output.txt) |
| `sessions_demo.py` | feature-demos | OpenAI | — | [output](feature-demos/sessions_demo.output.txt) |
| `add_source_provenance_demo.py` | feature-demos | OpenAI | — | [output](feature-demos/add_source_provenance_demo.output.txt) |
| `langgraph_direct_demo.py` | framework-demos | OpenAI | — | [output](framework-demos/langgraph_direct_demo.output.txt) |
| `langgraph_mcp_demo.py` | framework-demos | OpenAI | — | [output](framework-demos/langgraph_mcp_demo.output.txt) |
| `extraction_to_query_demo.py` | integration-demos | OpenAI | — | [output](integration-demos/extraction_to_query_demo.output.txt) |
| `full_lifecycle_demo.py` | integration-demos | OpenAI | — | [output](integration-demos/full_lifecycle_demo.output.txt) |
| `interactive_clarification_demo.py` | scenario-demos | OpenAI | — | [output](scenario-demos/interactive_clarification_demo.output.txt) |

Every script here is live-verified with real, captured output — unlike some of
kb-source's own OpenAI-gated demos, this session had a usable `OPENAI_API_KEY`
throughout. See [docs/README.md](../docs/README.md) for the rest of the project's
documentation.
