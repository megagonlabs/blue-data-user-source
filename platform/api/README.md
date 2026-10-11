# blue-userdb REST API

REST API for the user database — manage users, query their knowledge graphs, and handle webhook interactions over HTTP via FastAPI.

See [docs/api.md](../../docs/api.md) for the complete endpoint reference. This README covers installation, a quick start, and running this package's tests.

## Installation

The library is not yet published to PyPI. Install both packages from source:

```bash
# 1. Install the library (with optional extras for contact methods)
cd lib && pip install -e '.[webhook,email]' && cd ..

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
# Start the server (defaults: 127.0.0.1:8000, no auth, ~/.blue-userdb data dir)
blue-userdb-api

# Or with explicit configuration
BLUE_DATA_USER_SOURCE_DATA_DIR=/data/blue-userdb BLUE_DATA_USER_SOURCE_API_KEY=secret blue-userdb-api

# Interactive docs
open http://localhost:8000/docs
```

Create a user and query them:

```bash
# Create user (with file-backend defaults derived from BLUE_DATA_USER_SOURCE_DATA_DIR)
curl -X POST http://localhost:8000/databases/alice

# Query — omitting "session" auto-creates a new one; response includes session_id
curl -X POST http://localhost:8000/alice/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "What skills does alice have?"}'

# Continue the same session
curl -X POST http://localhost:8000/alice/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "What about remote roles?", "session": "<session_id from above>"}'

# Set metadata
curl -X PUT http://localhost:8000/alice/metadata/preferences.verbosity \
  -H 'Content-Type: application/json' \
  -d '{"value": "brief"}'
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `BLUE_DATA_USER_SOURCE_DATA_DIR` | `~/.blue-userdb` | Directory where database files are stored |
| `BLUE_DATA_USER_SOURCE_API_KEY` | _(empty — no auth)_ | API key required in `X-API-Key` header; leave unset to disable auth |
| `BLUE_DATA_USER_SOURCE_ALLOWED_ORIGINS` | _(empty)_ | Comma-separated browser origins, besides the API's own, allowed to make state-changing requests |
| `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | _(empty)_ | Path to `schema.json` for KB schema seeding |
| `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` | _(packaged `metadata_schema.json`)_ | Path to a custom metadata schema |
| `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` | _(packaged `contact_schema.json`)_ | Path to a custom contact schema |
| `BLUE_DATA_USER_SOURCE_HOST` | `127.0.0.1` | Server bind address |
| `BLUE_DATA_USER_SOURCE_PORT` | `8000` | Server port |

**Cross-origin writes.** A state-changing request (`POST`, `PUT`, `PATCH`, `DELETE`) that carries a browser `Origin` header other than the API's own or one listed in `BLUE_DATA_USER_SOURCE_ALLOWED_ORIGINS` is refused with `403`. Without it, any web page the operator visits could make the browser post to a local, keyless API, e.g. reset a user. Scripts and SDKs send no `Origin` and are unaffected.

Settings can also be loaded from a `.env` file in the working directory.

## Authentication

When `BLUE_DATA_USER_SOURCE_API_KEY` is set, every request must include:

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
| `POST` | `/databases/{name}` | Create a new user (file-backend defaults from `BLUE_DATA_USER_SOURCE_DATA_DIR`) |
| `GET` | `/databases/{name}` | Get user info and registry properties |
| `DELETE` | `/databases/{name}` | Delete a user and all their data |
| `POST` | `/databases/{name}/reset` | Clear a user's KB data, ingested documents, metadata, contacts and sessions, and reseed the schemas; the user stays registered |

`POST /databases/{name}` takes no body (an empty `{}` is accepted): every store is a file under `BLUE_DATA_USER_SOURCE_DATA_DIR/sources/{name}/`, and any other key is rejected with `422`. `name` must be 1–64 letters, digits, `_` or `-`, starting with a letter, digit or `_`. Other backends (Redis, Neo4j) are configured through the library or the CLI, not over REST.

### Query

| Method | Path | Description |
|---|---|---|
| `POST` | `/{name}/query` | Natural-language query against a user's knowledge graph |

**Request:**

```json
{
  "query": "What skills does alice have?",
  "output_form": "json",
  "session": "optional-session-id",
  "include_expanded": false
}
```

`output_form` is `"json"` (default) or `"nl"` for a prose answer. `session` appends this query to an existing session (reused); omit it to auto-create a new single-query session — **reuse-or-create**. `include_expanded` (default `false`) also returns the per-sub-question queries and their raw results alongside the synthesized answer.

**Response:**

```json
{
  "database": "alice",
  "query": "What skills does alice have?",
  "results": [...],
  "session_id": "1c1919ff-9881-4429-8c52-ab6abae6ff1a"
}
```

`session_id` is always present — the session that was reused, or the one just auto-created. When `include_expanded` is `true`, `results` becomes `{"result": ..., "expanded": [...]}` instead of the plain answer.

### Sessions

| Method | Path | Description |
|---|---|---|
| `POST` | `/{name}/sessions` | Create a new session |
| `GET` | `/{name}/sessions` | List sessions for a database |
| `GET` | `/{name}/sessions/{session_id}` | Get one session's queries and interactions |
| `POST` | `/{name}/sessions/{session_id}/end` | End a session |

```bash
# Start a session, then query within it
SID=$(curl -s -X POST http://localhost:8000/alice/sessions | jq -r .session_id)
curl -X POST http://localhost:8000/alice/query \
  -H 'Content-Type: application/json' \
  -d "{\"query\": \"What skills does alice have?\", \"session\": \"$SID\"}"

# Inspect and end it
curl http://localhost:8000/alice/sessions/$SID
curl -X POST http://localhost:8000/alice/sessions/$SID/end
```

`GET /{name}/sessions/{session_id}` returns `404` if unknown. `POST .../end` returns `404` if unknown; ending an already-ended session is idempotent (`200`). See [10-data-model.md](../../design/10-data-model.md) §6 for the full record schema.

### Data

| Method | Path | Description |
|---|---|---|
| `GET` | `/{name}/data` | List all ingested data entries |
| `GET` | `/{name}/sources` | List registered sources; optional `?source_id=` filter |
| `POST` | `/{name}/sources` | Add a source from text (no file uploads in 1.0) and optionally extract attributes |
| `DELETE` | `/{name}/sources/{source_name}` | Remove a source by name or id: its document leaves search and query answers; facts extracted from it are kept. Returns `{database, id, name, chunks_removed}`; `404` if no source, or more than one, matches |

`POST /{name}/sources` takes **text only** — `source` is the text to add (required), and it is never read as a path on the server. File uploads are not supported over REST in 1.0; add files with the CLI (`blue-userdb data source add FILE`) or the MCP `add_source` tool. Body:

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
| `PATCH` | `/{name}/contacts/{protocol}/{contact_name}` | Update details or preference: `details` replaces the stored fields (the preference is kept unless given); a secret field sent back masked as `***` keeps its stored value |
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

See [Email contact method](#email-contact-method) below for all detail keys.

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
| `POST` | `/interactions/{interaction_id}/response` | Resolve a pending interaction via JSON (webhook / REST) |
| `GET` | `/interactions/{interaction_id}/respond` | HTML form for responding (link in email body) |
| `POST` | `/interactions/{interaction_id}/respond` | Submit the HTML form response |
| `POST` | `/interactions/email/inbound` | Inbound email webhook — resolves a pending email interaction |

**`POST /interactions/{interaction_id}/response`** — used by webhooks and direct API callers:

```json
{"text": "Use the home address please."}
```

Returns `404` if the interaction ID is unknown or has already timed out, `409` if already resolved.

**`GET /interactions/{interaction_id}/respond`** — HTML form served to users who click the link in an email. No API key required; the interaction ID acts as a bearer token. Returns `404` if the interaction has expired.

**`POST /interactions/email/inbound?provider=<name>`** — accepts inbound email webhooks from Mailgun, Postmark, or Sendgrid and resolves the corresponding pending Future. No API key required.

| `provider` | Payload format | Reply text field |
|---|---|---|
| `mailgun` | `application/x-www-form-urlencoded` | `stripped-text` / `body-plain` fallback |
| `postmark` | `application/json` | `StrippedTextReply` / `TextBody` fallback |
| `sendgrid` | `application/x-www-form-urlencoded` | `text` (client-side quote stripping) |

Configure your inbound email provider to route mail addressed to `interaction-*@{reply_domain}` to `POST /interactions/email/inbound?provider=<name>`. Delivery is idempotent — duplicate POSTs for the same interaction are accepted without error.

---

## Email contact method

Requires `pip install -e '../../lib[email]'` (`aiosmtplib`).

When the agent needs to contact a user, it sends an SMTP email with:
- `Reply-To: interaction-{id}@{reply_domain}` — so a direct email reply routes back through the inbound webhook
- A clickable link to `{response_base_url}/interactions/{interaction_id}/respond` — as a fallback for clients that don't support direct reply-to

Detail keys for the `email` protocol:

| Key | Required | Default | Description |
|---|---|---|---|
| `address` | yes | — | Recipient email address |
| `inbound_provider` | no | _(none)_ | `mailgun`, `postmark`, `sendgrid`, `smtp_server`, or `stdio` |
| `from_address` | yes¹ | `"agent"` | Sender shown in From: |
| `smtp_host` | yes¹ | — | SMTP server hostname |
| `smtp_port` | no | `587` | SMTP port |
| `smtp_user` | no | `from_address` | SMTP auth username |
| `smtp_password` | no | `""` | SMTP auth password. Masked on reads; may be a `$VAR` reference |
| `smtp_use_tls` | no | `True` | Use STARTTLS |
| `reply_domain` | yes¹ | `"localhost"` | Domain for `Reply-To` address |
| `response_base_url` | yes¹ | — | Base URL of this API server |
| `subject` | no | `"A question for you"` | Email subject |
| `timeout` | no | `300` | Seconds to wait for reply |

¹ Not required when `inbound_provider` is `"stdio"`.

**Secrets.** `smtp_password`, a webhook's `url` and `headers`, and a notification `endpoint` are secret: every read path (REST, MCP tools, `blue-userdb contact list/get`) returns them masked as `***`. To keep them out of the contacts store too, store a reference to an environment variable instead, e.g. `"smtp_password": "$SMTP_PASSWORD"`; it is resolved when a message is sent, and shown as-is on reads.

**`inbound_provider: "stdio"`** — development mode: prints email content to stdout and reads reply from stdin. Useful for local testing without an SMTP server or inbound webhook.

```bash
# Add a stdio email contact for local testing
curl -X POST http://localhost:8000/alice/contacts \
  -H 'Content-Type: application/json' \
  -d '{
    "protocol": "email",
    "name": "dev",
    "details": {
      "address": "alice@example.com",
      "inbound_provider": "stdio"
    }
  }'
```

---

## Storage layout

Data is persisted under `BLUE_DATA_USER_SOURCE_DATA_DIR` (default `~/.blue-userdb`):

```
~/.blue-userdb/
├── registry.json              # outer DataRegistry store (users + source properties)
├── registries/
│   └── alice.json             # per-user DataRegistry store
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
