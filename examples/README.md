# blue-data-user-source Examples

This directory contains runnable examples organized by purpose, mirroring the sibling
[`blue-data-kb-source/examples/`](../../blue-data-kb-source/examples/) layout.

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

> **Gotcha surfaced by this demo:** `RedisJSONSource.get()` (in the sibling `blue-data`
> package) returns `[]`, not `None`, for a missing JSONPath. `seed_metadata_schema`/
> `seed_contact_schema`'s idempotency check (`if get(...) is None`) reads that as
> "already seeded," so under Redis only the *first* metadata category (`identity`) and
> first contact protocol (`email`) actually get seeded — the rest silently don't. The
> demo scopes itself to what actually round-trips and documents this precisely inline;
> see `file_backend_demo.py` for the full, unaffected picture. This is an upstream
> (`blue-data`) bug, not touched by this example.

---

## feature-demos/ — one feature per script

Each script is a short, single-feature deep dive (most are calling only one or two
library entry points end to end).

| Script | Demonstrates |
|---|---|
| [`query_rewrite_demo.py`](feature-demos/query_rewrite_demo.py) | `contextualize_query`'s self-reference → user-name substitution; `expand_query`'s KB-schema-grounded, zero-or-more sub-questions (ADR-020/021) |
| [`output_formats_demo.py`](feature-demos/output_formats_demo.py) | One question, three ways: `output_form="json"`, `"nl"`, and `include_expanded=True` |
| [`metadata_demo.py`](feature-demos/metadata_demo.py) | Metadata schema auto-seeding on user creation, get/set/delete, and `availability.by_topic` per-topic overrides (ADR-023) |
| [`contact_resolution_demo.py`](feature-demos/contact_resolution_demo.py) | `ContactManager.identify_contact_method` choosing among several methods — single-method shortcut vs. LLM choice weighing `out_of_office`/`working_hours`/`preferred_channel`/topic overrides |
| [`sessions_demo.py`](feature-demos/sessions_demo.py) | `execute_query`'s reuse-or-create session semantics, and the `QueryError` on querying an ended session |
| [`add_source_provenance_demo.py`](feature-demos/add_source_provenance_demo.py) | `add_source` provenance-only registration (Type 1, no `queries`) vs. LLM extraction into the KB (Type 2, with `queries`) |

Run any of them directly, e.g.:

```bash
python3 examples/feature-demos/metadata_demo.py   # the one demo that needs no API key
```

**Requires:** `OPENAI_API_KEY` for all except `metadata_demo.py` (pure metadata CRUD,
no LLM call) | sample output alongside each script as `<name>.output.txt`

---

## framework-demos/ — agentic framework integrations

Both scripts use [LangGraph](https://github.com/langchain-ai/langgraph), following the
sibling `blue-data-kb-source` repo's own framework-demos precedent, and contrast two
ways to put an LLM agent in front of a user's data.

### Direct Python API (`langgraph_direct_demo.py`)

A 2-node LangGraph pipeline (`lookup` → `respond`) built directly on
`UserSource.execute_query_nl` — no MCP server involved.

```bash
pip install langgraph langchain-openai
python3 examples/framework-demos/langgraph_direct_demo.py
```

**Requires:** `OPENAI_API_KEY` | **[Sample output](framework-demos/langgraph_direct_demo.output.txt)**

### MCP-based integration (`langgraph_mcp_demo.py`)

No UserSource-specific code on the LangGraph side at all — a `create_react_agent` ReAct
agent freely chooses among all 23 tools auto-discovered via `langchain-mcp-adapters`
from the real `blue-data-user-mcp` server (the `udb-mcp` console script), launched
automatically as a subprocess over stdio.

```bash
pip install langgraph langchain-openai langchain-mcp-adapters
pip install -e platform/mcp/
python3 examples/framework-demos/langgraph_mcp_demo.py
```

**Requires:** `OPENAI_API_KEY` | **[Sample output](framework-demos/langgraph_mcp_demo.output.txt)**

---

## integration-demos/ — a couple of features working together

### Extraction feeds querying (`extraction_to_query_demo.py`)

`add_source(queries=...)` extraction populates a user's knowledge base, then
`execute_query` queries the result — chaining write-side LLM extraction and read-side
querying against the same source, which the single-feature demos above don't.

```bash
python3 examples/integration-demos/extraction_to_query_demo.py
```

**Requires:** `OPENAI_API_KEY` | **[Sample output](integration-demos/extraction_to_query_demo.output.txt)**

### Full lifecycle (`full_lifecycle_demo.py`)

Create a user → seed metadata → register a contact method → extract a source → run a
two-query session → inspect and end the session — the "everything together" walkthrough,
the direct analog of kb-source's own integration-demos hero script.

```bash
python3 examples/integration-demos/full_lifecycle_demo.py
```

**Requires:** `OPENAI_API_KEY` | **[Sample output](integration-demos/full_lifecycle_demo.output.txt)**

---

## scenario-demos/ — value proposition demos

### Resolving missing data through interactive clarification (`interactive_clarification_demo.py`)

**Problem:** a query can need information a user's data store simply doesn't have yet.
Returning an incomplete answer — or silently guessing — would be wrong.

**Solution:** `execute_query`'s completeness check (ADR-022's assess→interact→reassess
loop) evaluates the aggregated result, and if it fails, asks the user directly through
their preferred contact method before giving up, then re-checks — the caller never sees
any of this, it's all inside one `execute_query` call. This demo seeds a partial profile
(job title, experience — no compensation data), asks a question that needs the missing
piece, and lets a real OpenAI-scored `CompletenessMetric` genuinely decide whether to
trigger the interaction (nothing is scripted around a fake evaluation — only the user's
stdio reply is scripted, so the demo can run unattended).

```bash
python3 examples/scenario-demos/interactive_clarification_demo.py
```

**Requires:** `OPENAI_API_KEY` | **[Sample output](scenario-demos/interactive_clarification_demo.output.txt)**

> **Gotcha surfaced by this demo:** `FreshnessMetric` (evaluated alongside
> `CompletenessMetric` on every round) scores off `modified`/`created` timestamps that
> only land in `query_results_metadata` when the KB answer-agent happens to call
> `get_metadata` for that lookup — which it doesn't reliably do. With no timestamps at
> all, freshness scores `0.0` and can never pass, regardless of what the user answers.
> In a real deployment with `max_interaction_rounds > 1`, this can burn every remaining
> round on an unresolvable metric even after the metric that actually needed the user's
> input has already passed. See the demo's own trailing output for the live evidence.

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
