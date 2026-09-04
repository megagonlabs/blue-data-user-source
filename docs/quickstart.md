# Quick Start

The fastest way to see it in action is the `udb` CLI — no Python code required. See [installation.md](installation.md) if you haven't installed anything yet.

```bash
pip install -e ../blue-data/lib
pip install -e ../blue-data-kb-source/lib
pip install -e ../blue-data-doc-source/lib
cd lib && pip install -e . && cd ..
cd platform/cli && pip install -e . && cd ../..

export OPENAI_API_KEY=sk-...
```

## 1. Create a database and select it

Databases (one per user) persist under `~/.udb/` by default (override with `export BLUE_DATA_USER_SOURCE_DATA_DIR=/path/to/dir`). `create` auto-selects the new database.

```bash
udb database create alice
```

## 2. Register a data source

A file is always parsed, chunked, and embedded for later search — that alone is Type 1 (source registration). Add `--query` flags to also extract specific attributes into the knowledge graph via an LLM agent (Type 2):

```bash
# Type 1 — register only
udb data source add resume.txt

# Type 2 — register + extract
udb data source add resume.txt \
    --query "What skills does the user have?" \
    --query "What is the user's most recent job title?"
```

## 3. Query

```bash
udb data query "What jobs are suitable for me?"
```

```
 Query                               Results
 What skills does the user have?     Python, SQL, machine learning
 Does the user prefer remote work?   Yes
```

`execute_query` rewrites the query (resolving "me"/"you" to the user's actual name), expands it into schema-grounded sub-questions, retrieves data for each from the knowledge graph and any registered documents, and assesses the combined result for completeness and freshness — asking a clarification question if quality checks fail.

```bash
udb data query "What jobs are suitable for me?" --format nl
```

## 4. Group queries into a session

A session ties multiple queries and their clarification interactions into one conversation, giving later queries context from earlier ones.

```bash
udb session start
udb data query "What jobs are suitable for me?"    # continues the selected session
udb data query "What about remote roles?"          # same session
udb session show                                    # see queries and interactions
udb session end
```

## 5. Look at what you built

```bash
udb data list
udb data source list
```

---

## Using the library directly

Everything above is a thin wrapper over the Python library. The same walkthrough in code:

```python
import asyncio
from blue_data_user_source import FileUserSource

async def main():
    us = FileUserSource("us", {"connection": {"path": "~/.udb/registry.json"}})

    await us.create_user(
        "alice",
        registry_props={"_class": "blue_data.source.json.file_json_source.FileJSONSource",
                         "connection": {"protocol": "json/file", "path": "~/.udb/registries/alice.json"}},
        kb_source_props={"_class": "blue_data_kb_source.file_kb_source.FileKBSource",
                          "connection": {"protocol": "kb/file", "directory": "~/.udb/sources/alice"}},
        metadata_source_props={"_class": "blue_data.source.json.file_json_source.FileJSONSource",
                                "connection": {"protocol": "json/file", "path": "~/.udb/sources/alice/metadata.json"}},
        contact_source_props={"_class": "blue_data.source.json.file_json_source.FileJSONSource",
                               "connection": {"protocol": "json/file", "path": "~/.udb/sources/alice/contacts.json"}},
        session_source_props={"_class": "blue_data.source.json.file_json_source.FileJSONSource",
                               "connection": {"protocol": "json/file", "path": "~/.udb/sources/alice/sessions.json"}},
    )

    await us.add_source("resume.txt", database="alice")

    results, session_id = us.execute_query("jobs suitable for me", database="alice")
    for r in results:
        print(r.query, "→", r.results)

asyncio.run(main())
```

See [guide.md](guide.md) for the full walkthrough (contact methods, metadata, sessions) and [api-reference.md](api-reference.md) for every method.

---

## Connecting an LLM agent (MCP)

To let Claude or another MCP client create users and query their knowledge stores directly:

```bash
cd platform/mcp && bash scripts/install.sh
udb-mcp
```

```json
{
  "mcpServers": {
    "blue-data-user": { "command": "udb-mcp" }
  }
}
```

See [mcp.md](mcp.md) for the Claude Desktop config and full tool reference.

---

## Using the REST API

```bash
cd platform/api && bash scripts/install.sh
udb-api
```

```bash
curl -X POST http://localhost:8000/databases/alice

curl -X POST http://localhost:8000/alice/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "What skills does alice have?"}'
```

See [api.md](api.md) for every endpoint.

---

## Next steps

- [features.md](features.md) — what the library can do, at a glance
- [guide.md](guide.md) — task-oriented walkthrough of the Python API
- [cli.md](cli.md) / [mcp.md](mcp.md) / [api.md](api.md) — full command/tool/endpoint references
