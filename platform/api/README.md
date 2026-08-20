# udb REST API

REST API for the user database — manage users, query their knowledge graphs, and handle webhook interactions over HTTP via FastAPI.

## Installation

The library is not yet published to PyPI. Install both packages from source:

```bash
# 1. Install the library
cd lib && pip install -e '.[webhook]' && cd ..

# 2. Install the API server
cd platform/api && pip install -e .
```

`fastapi`, `uvicorn`, `httpx`, and `pydantic-settings` are pulled in automatically.

Set your OpenAI API key if you plan to use query endpoints:

```bash
export OPENAI_API_KEY=sk-...
```

## Quick start

```bash
# Start the server (defaults: 127.0.0.1:8000, no auth, ~/.udb data dir)
udb-api

# Or with explicit configuration
UDB_DATA_DIR=/data/udb UDB_API_KEY=secret udb-api

# Interactive docs
open http://localhost:8000/docs
```

Create a user and query them:

```bash
# Create user (with file-backend defaults derived from UDB_DATA_DIR)
curl -X POST http://localhost:8000/databases/alice

# Query
curl -X POST http://localhost:8000/alice/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "What skills does alice have?"}'

# Set metadata
curl -X PUT http://localhost:8000/alice/metadata/preferences.verbosity \
  -H 'Content-Type: application/json' \
  -d '{"value": "brief"}'
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `UDB_DATA_DIR` | `~/.udb` | Directory where database files are stored |
| `UDB_API_KEY` | _(empty — no auth)_ | API key required in `X-API-Key` header; leave unset to disable auth |
| `UDB_SCHEMA_PATH` | _(empty)_ | Path to `schema.json` for KB schema seeding |
| `UDB_HOST` | `127.0.0.1` | Server bind address |
| `UDB_PORT` | `8000` | Server port |

Settings can also be loaded from a `.env` file in the working directory.

## Authentication

When `UDB_API_KEY` is set, every request must include:

```
X-API-Key: <your-key>
```

Requests without a valid key receive `401 Unauthorized`. When the env var is unset, authentication is disabled.

---

## Endpoints

### System

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check — returns `{"status": "ok"}` |

### Databases (users)

| Method | Path | Description |
|---|---|---|
| `GET` | `/databases` | List all registered users |
| `POST` | `/databases/{name}` | Create a new user (file-backend defaults from `UDB_DATA_DIR`) |
| `GET` | `/databases/{name}` | Get user info and registry properties |
| `DELETE` | `/databases/{name}` | Delete a user and all their data |
| `POST` | `/databases/{name}/reset` | Reset KB data for a user and reseed the schema |

`POST /databases/{name}` accepts an optional JSON body to override the default file paths:

```json
{
  "registry":        {"_class": "...", "connection": {...}},
  "kb_source":       {"_class": "...", "connection": {...}},
  "metadata_source": {"_class": "...", "connection": {...}},
  "contact_source":  {"_class": "...", "connection": {...}}
}
```

Omit any key to use the file-backend default derived from `UDB_DATA_DIR/sources/{name}/`.

### Query

| Method | Path | Description |
|---|---|---|
| `POST` | `/{name}/query` | Natural-language query against a user's knowledge graph |

```json
{
  "query": "What skills does alice have?",
  "output_form": "json",
  "session": "optional-session-id"
}
```

`output_form` is `"json"` (default) or `"nl"` for a prose answer.

### Data

| Method | Path | Description |
|---|---|---|
| `GET` | `/{name}/data` | List all ingested data entries |
| `GET` | `/{name}/sources` | List registered sources; optional `?source_id=` filter |
| `POST` | `/{name}/sources` | Add a source and optionally extract attributes |
| `DELETE` | `/{name}/sources/{source_name}` | Remove a source from the registry (KB data preserved) |

`POST /{name}/sources` body:

```json
{
  "source": "Alice joined Acme Corp in 2019 as a data scientist.",
  "name": "resume",
  "description": "Alice's resume",
  "queries": ["What role does Alice have?", "What year did she join Acme?"]
}
```

### Metadata

| Method | Path | Description |
|---|---|---|
| `GET` | `/{name}/metadata` | List all metadata keys and values |
| `GET` | `/{name}/metadata/{key}` | Get a metadata value (nested keys use `.` separator) |
| `PUT` | `/{name}/metadata/{key}` | Set a metadata value |
| `DELETE` | `/{name}/metadata/{key}` | Delete a metadata key |

```bash
curl -X PUT http://localhost:8000/alice/metadata/preferences.verbosity \
  -H 'Content-Type: application/json' \
  -d '{"value": "brief"}'
```

### Contacts

| Method | Path | Description |
|---|---|---|
| `GET` | `/{name}/contacts` | List contact methods; optional `?protocol=` filter |
| `POST` | `/{name}/contacts` | Add a contact method |
| `GET` | `/{name}/contacts/{protocol}/{contact_name}` | Get a specific contact method |
| `PATCH` | `/{name}/contacts/{protocol}/{contact_name}` | Update details or preference |
| `DELETE` | `/{name}/contacts/{protocol}/{contact_name}` | Remove a contact method |

`POST /{name}/contacts` body:

```json
{
  "protocol": "email",
  "name": "work",
  "details": {"address": "alice@example.com"},
  "preference": 1
}
```

Webhook contact method example:

```json
{
  "protocol": "webhook",
  "name": "slack-bot",
  "details": {
    "url": "https://hooks.example.com/incoming",
    "response_base_url": "http://localhost:8000",
    "timeout": 300
  }
}
```

When an agent needs to ask Alice a question, the webhook fires a `POST` to `url` with:

```json
{
  "interaction_id": "<uuid>",
  "message": "Which delivery address should I use?",
  "response_url": "http://localhost:8000/interactions/<uuid>/response"
}
```

The external system posts Alice's reply back to `response_url`, unblocking the waiting agent.

### Interactions

| Method | Path | Description |
|---|---|---|
| `POST` | `/interactions/{id}/response` | Post a human reply to a pending webhook interaction |

```json
{"text": "Use the home address please."}
```

Returns `404` if the interaction ID is unknown or has already timed out, `409` if it was already resolved.

---

## Storage layout

Data is persisted under `UDB_DATA_DIR` (default `~/.udb`):

```
~/.udb/
├── registry.json              # outer DataRegistry store (users + source properties)
├── registries/
│   └── alice.json             # per-user DataRegistry store
└── sources/
    └── alice/
        ├── alice.json         # per-user knowledge graph (file KB backend)
        ├── metadata.json      # user metadata
        └── contacts.json      # user contact methods
```

---

## Running tests

```bash
cd platform/api
pytest
```
