# Quick Start

The fastest way to see it in action is the `blue-userdb` CLI — no Python code required. See [installation.md](installation.md) if you haven't installed anything yet.

```bash
# The sibling repos (cloned beside this one), the library and the CLI
bash platform/cli/scripts/install.sh       # or scripts/install.sh for the MCP server and REST API too

export OPENAI_API_KEY=sk-...
```

> **Cost.** Each query and each `--query` extraction makes dozens of OpenAI calls. At the default model (gpt-4o), this walkthrough cost about $7 in testing, mostly its four queries ($0.60–$2 each). To spend less, add `--max-subqueries 1 --max-kb-turns 8` to `data query`, and see [Cost](guide.md#cost) for cheaper model settings.

## 1. Create a database and select it

Databases (one per user) persist under `~/.blue-userdb/` by default (override with `blue-userdb profile config BLUE_DATA_USER_SOURCE_DATA_DIR /path/to/dir`, or by exporting `BLUE_DATA_USER_SOURCE_DATA_DIR`). `create` auto-selects the new database.

```bash
blue-userdb database create alice        # add --no-onboard to skip the questions
```

## 2. Register a data source

A file is always parsed, chunked, and embedded for later search — that alone is Type 1 (source registration). Add `--query` flags to also extract specific attributes into the knowledge graph via an LLM agent (Type 2):

```bash
# Type 1 — register only
blue-userdb data source add data/resume.txt

# Type 2 — register + extract
blue-userdb data source add data/resume.txt \
    --query "What skills does the user have?" \
    --query "What is the user's most recent job title?"
```

Adding a file that is already a source, as the Type 2 step does here, updates that source instead of adding a second one: its chunks are replaced by the new ingest (so an edited file is picked up), and the extraction is recorded under it. The same file under another `--name` is another source.

## 3. Query

```bash
blue-userdb data query "What jobs are suitable for me?"
```

```
 Query                               Results
 What skills does the user have?     Python, SQL, machine learning
 Does the user prefer remote work?   Yes
```

`execute_query` rewrites the query (resolving "me"/"you" to the user's actual name), expands it into schema-grounded sub-questions, retrieves data for each from the knowledge graph and any registered documents, and assesses the combined result for completeness and freshness — asking a clarification question if quality checks fail.

```bash
blue-userdb data query "What jobs are suitable for me?" --format nl
```

## 4. Group queries into a session

A session ties multiple queries and their clarification interactions into one conversation, giving later queries context from earlier ones.

```bash
blue-userdb session start
blue-userdb data query "What jobs are suitable for me?"    # continues the selected session
blue-userdb data query "What about remote roles?"          # same session
blue-userdb session show                                    # see queries and interactions
blue-userdb session end
```

## 5. Look at what you built

```bash
blue-userdb data list
blue-userdb data source list
```

---

## Using the library directly

Everything above is a thin wrapper over the Python library. The same walkthrough in code:

```python
import asyncio
from blue_data_user_source import FileUserSource

async def main():
    # A directory of its own: the CLI, MCP and REST servers keep their users
    # under ~/.blue-userdb, and an "alice" there would share these files.
    us = FileUserSource("us", {"connection": {"path": "~/.blue-userdb-lib/registry.json"}})

    # The CLI's file layout, under ~/.blue-userdb-lib (see guide.md to choose each store)
    us.create_database("alice")

    await us.add_source("data/resume.txt", database="alice")

    answer, session_id = await us.async_execute_query("jobs suitable for me", database="alice")
    print(answer)

asyncio.run(main())
```

See [guide.md](guide.md) for the full walkthrough (contact methods, metadata, sessions) and [api-reference.md](api-reference.md) for every method.

---

## Connecting an LLM agent (MCP)

To let Claude or another MCP client create users and query their knowledge stores directly:

```bash
cd platform/mcp && bash scripts/install.sh
blue-userdb-mcp
```

```json
{
  "mcpServers": {
    "blue-data-user": { "command": "blue-userdb-mcp" }
  }
}
```

See [mcp.md](mcp.md) for the Claude Desktop config and full tool reference.

---

## Using the REST API

```bash
cd platform/api && bash scripts/install.sh
export BLUE_DATA_USER_API_KEY=secret   # required; or BLUE_DATA_USER_API_AUTH_DISABLED=true for local use
blue-userdb-api                        # http://127.0.0.1:8003
```

```bash
curl -H "X-API-Key: $BLUE_DATA_USER_API_KEY" -X POST http://localhost:8003/databases/alice

curl -H "X-API-Key: $BLUE_DATA_USER_API_KEY" -X POST http://localhost:8003/alice/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "What skills does alice have?"}'
```

See [api.md](api.md) for every endpoint.

---

## Next steps

- [features.md](features.md) — what the library can do, at a glance
- [guide.md](guide.md) — task-oriented walkthrough of the Python API
- [cli.md](cli.md) / [mcp.md](mcp.md) / [api.md](api.md) — full command/tool/endpoint references
