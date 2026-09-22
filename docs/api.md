# blue-data-user-api — REST API

REST API for the user database — manage users, query their knowledge graphs, and handle webhook/email interactions over HTTP via FastAPI. Endpoints map 1:1 to Python library operations; no business logic lives in the route handlers. For the Python library reference underneath these endpoints, see [api-reference.md](api-reference.md).

---

## Installation

```bash
cd platform/api
bash scripts/install.sh
```

Or manually, with optional contact-method extras on the library:

```bash
pip install -e '../../lib[webhook,email]'
pip install -e .
```

`fastapi`, `uvicorn`, `httpx`, and `pydantic-settings` are pulled in automatically.

```bash
export OPENAI_API_KEY=sk-...
```

---

## Running

```bash
# Defaults: 127.0.0.1:8000, no auth, ~/.blue-userdb data dir
blue-userdb-api

# Or with explicit configuration
BLUE_DATA_USER_SOURCE_DATA_DIR=/data/blue-userdb BLUE_DATA_USER_SOURCE_API_KEY=secret blue-userdb-api

# Bind to all interfaces (scripts/start.sh does this by default)
bash scripts/start.sh

# Interactive docs
open http://localhost:8000/docs
```

Settings can also be loaded from a `.env` file in the working directory (`pydantic-settings`).

## Configuration reference

These share their names with the `blue-userdb` CLI's profile parameters but nothing else: the server reads the environment only, never `~/.blue-userdb/.profiles` or the selected profile. A CLI profile cannot reconfigure a running server.

| Variable | Default | Description |
|---|---|---|
| `BLUE_DATA_USER_SOURCE_DATA_DIR` | `~/.blue-userdb` | Directory where database files are stored |
| `BLUE_DATA_USER_SOURCE_API_KEY` | _(empty — no auth)_ | API key required in `X-API-Key` header; unset disables auth |
| `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | _(empty)_ | Path to a custom `schema.json` for KB schema seeding |
| `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` | _(packaged `metadata_schema.json`)_ | Path to a custom metadata schema |
| `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` | _(packaged `contact_schema.json`)_ | Path to a custom contact schema |
| `BLUE_DATA_USER_SOURCE_HOST` | `127.0.0.1` | Server bind address |
| `BLUE_DATA_USER_SOURCE_PORT` | `8000` | Server port |

## Authentication

When `BLUE_DATA_USER_SOURCE_API_KEY` is set, every request must include:

```
X-API-Key: <your-key>
```

Requests without a valid key receive `401 Unauthorized`. When the env var is unset, authentication is disabled entirely.

---

## Endpoints

### System

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check — `{"status": "ok"}` |

### Databases (users)

| Method | Path | Description |
|---|---|---|
| `GET` | `/databases` | List all registered users |
| `POST` | `/databases/{name}` | Create a new user (file-backend defaults from `BLUE_DATA_USER_SOURCE_DATA_DIR`) |
| `GET` | `/databases/{name}` | Get user info and registry properties |
| `DELETE` | `/databases/{name}` | Delete a user and all their data |
| `POST` | `/databases/{name}/reset` | Reset KB data for a user and reseed the schema (metadata/contacts preserved) |

`POST /databases/{name}` accepts an optional JSON body to override the default file paths — omit any key to fall back to `BLUE_DATA_USER_SOURCE_DATA_DIR/sources/{name}/`:

```json
{
  "registry":        {"_class": "...", "connection": {...}},
  "kb_source":       {"_class": "...", "connection": {...}},
  "metadata_source": {"_class": "...", "connection": {...}},
  "contact_source":  {"_class": "...", "connection": {...}},
  "session_source":  {"_class": "...", "connection": {...}},
  "doc_source":      {"embedding_model": "dummy", "vector_source": {"backend": "file", "directory": "..."}}
}
```

### Query

| Method | Path | Description |
|---|---|---|
| `POST` | `/{name}/query` | Natural-language query against a user's knowledge graph |

**Request:**

```json
{
  "query": "What skills does alice have?",
  "output_form": "json",
  "session": "optional-session-id"
}
```

`output_form` is `"json"` (default) or `"nl"` for a prose answer. `session` appends this query to an existing session (reused, `404` if unknown/ended); omit it to auto-create a new single-query session.

**Response `200 OK`:**

```json
{
  "database": "alice",
  "query": "What skills does alice have?",
  "results": [
    {"query": "What skills does the user have?", "results": ["Python", "SQL", "machine learning"]}
  ],
  "session_id": "1c1919ff-9881-4429-8c52-ab6abae6ff1a"
}
```

`session_id` is always present — the session that was reused, or the one just auto-created.

### Sessions

| Method | Path | Description |
|---|---|---|
| `POST` | `/{name}/sessions` | Create a new session |
| `GET` | `/{name}/sessions` | List sessions for a database |
| `GET` | `/{name}/sessions/{session_id}` | Get one session's queries and interactions |
| `POST` | `/{name}/sessions/{session_id}/end` | End a session |

```bash
SID=$(curl -s -X POST http://localhost:8000/alice/sessions | jq -r .session_id)
curl -X POST http://localhost:8000/alice/query \
  -H 'Content-Type: application/json' \
  -d "{\"query\": \"What skills does alice have?\", \"session\": \"$SID\"}"

curl http://localhost:8000/alice/sessions/$SID
curl -X POST http://localhost:8000/alice/sessions/$SID/end
```

`GET .../sessions/{id}` returns `404` if unknown. `POST .../end` returns `404` if unknown; ending an already-ended session is idempotent (`200`). See [10-data-model.md](../design/10-data-model.md) §6 for the full record schema.

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
  "details": {
    "address": "alice@example.com",
    "from_address": "agent@blue-userdb.example.com",
    "smtp_host": "smtp.example.com",
    "reply_domain": "blue-userdb.example.com",
    "response_base_url": "http://localhost:8000",
    "inbound_provider": "mailgun"
  },
  "preference": 1
}
```

Webhook contact method:

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
| `POST` | `/interactions/{interaction_id}/response` | Resolve a pending interaction via JSON (webhook / REST) |
| `GET` | `/interactions/{interaction_id}/respond` | HTML form for responding (link in email body) |
| `POST` | `/interactions/{interaction_id}/respond` | Submit the HTML form response |
| `POST` | `/interactions/email/inbound` | Inbound email webhook — resolves a pending email interaction |

**`POST /interactions/{interaction_id}/response`** (used by webhooks and direct API callers):

```json
{"text": "Use the home address please."}
```

Returns `404` if the interaction ID is unknown or has already timed out, `409` if already resolved.

**`GET /interactions/{interaction_id}/respond`** — HTML form served to users who click the link in an email. No API key required; the interaction ID acts as a bearer token. Returns `404` if the interaction has expired.

**`POST /interactions/email/inbound?provider=<name>`** — accepts inbound email webhooks and resolves the corresponding pending interaction. No API key required.

| `provider` | Payload format | Reply text field |
|---|---|---|
| `mailgun` | `application/x-www-form-urlencoded` | `stripped-text` / `body-plain` fallback |
| `postmark` | `application/json` | `StrippedTextReply` / `TextBody` fallback |
| `sendgrid` | `application/x-www-form-urlencoded` | `text` (client-side quote stripping) |

Configure your inbound email provider to route mail addressed to `interaction-*@{reply_domain}` to `POST /interactions/email/inbound?provider=<name>`. Delivery is idempotent — duplicate POSTs for the same interaction are accepted without error.

---

## Email contact method

Requires `pip install -e '../../lib[email]'` (`aiosmtplib`).

When the agent needs to contact a user, it sends an SMTP email with a `Reply-To: interaction-{id}@{reply_domain}` header (so a direct reply routes back through the inbound webhook) and a clickable link to `{response_base_url}/interactions/{interaction_id}/respond` as a fallback.

| Key | Required | Default | Description |
|---|---|---|---|
| `address` | yes | — | Recipient email address |
| `inbound_provider` | no | _(none)_ | `mailgun`, `postmark`, `sendgrid`, `smtp_server`, or `stdio` |
| `from_address` | yes¹ | `"agent"` | Sender shown in From: |
| `smtp_host` | yes¹ | — | SMTP server hostname |
| `smtp_port` | no | `587` | SMTP port |
| `smtp_user` | no | `from_address` | SMTP auth username |
| `smtp_password` | no | `""` | SMTP auth password |
| `smtp_use_tls` | no | `True` | Use STARTTLS |
| `reply_domain` | yes¹ | `"localhost"` | Domain for `Reply-To` address |
| `response_base_url` | yes¹ | — | Base URL of this API server |
| `subject` | no | `"A question for you"` | Email subject |
| `timeout` | no | `300` | Seconds to wait for reply |

¹ Not required when `inbound_provider` is `"stdio"`.

**`inbound_provider: "stdio"`** — development mode: prints email content to stdout and reads the reply from stdin. Useful for local testing without an SMTP server or inbound webhook.

```bash
curl -X POST http://localhost:8000/alice/contacts \
  -H 'Content-Type: application/json' \
  -d '{
    "protocol": "email",
    "name": "dev",
    "details": {"address": "alice@example.com", "inbound_provider": "stdio"}
  }'
```

`smtp_server` is reserved for a future `aiosmtpd`-based inbound listener — currently raises `NotImplementedError` if selected.

---

## Error responses

All errors use a consistent envelope. FastAPI exception handlers catch `UDbError` subtypes and map them to these responses — no error-handling logic lives in route handlers.

```json
{
  "error": {
    "code": "query_error",
    "message": "No database specified and no default configured."
  }
}
```

| HTTP status | `code` | Condition |
|---|---|---|
| 400 | `invalid_request` | Malformed request body |
| 404 | `database_not_found` | Specified database does not exist |
| 422 | `query_error` | Query could not be processed |
| 422 | `import_error` | Import failed |
| 500 | `internal_error` | Unexpected failure |

---

## Storage layout

Data is persisted under `BLUE_DATA_USER_SOURCE_DATA_DIR` (default `~/.blue-userdb`):

```
~/.blue-userdb/
├── registry.json              # outer registry (users + source properties)
├── registries/
│   └── alice.json             # per-user registry
└── sources/
    └── alice/
        ├── alice.json         # per-user knowledge graph (file KB backend)
        ├── metadata.json      # user metadata
        ├── contacts.json      # user contact methods
        ├── sessions.json      # session / query / interaction records
        └── sessions/          # per-session interaction transcripts (file vector backend)
```

---

## Running tests

```bash
cd platform/api
pytest
```
