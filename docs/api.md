# blue-data-user-api — REST API

REST API for the user database — manage users, query their knowledge graphs, and handle webhook/email interactions over HTTP via FastAPI. Endpoints map 1:1 to Python library operations; no business logic lives in the route handlers. For the Python library reference underneath these endpoints, see [api-reference.md](api-reference.md).

---

## Installation

```bash
cd platform/api
bash scripts/install.sh
```

The script installs the library first with `lib/scripts/install.sh`, which installs the sibling repos (`blue-data`, `blue-data-kb-source`, `blue-data-doc-source`) from checkouts beside this repo: none of them is on PyPI. Or step by step, from `platform/api`:

```bash
bash ../../lib/scripts/install.sh   # the sibling repos, then the library with its webhook and email extras
pip install -e '.[dev]'             # the server, with pytest for its tests
```

`fastapi`, `uvicorn`, `httpx`, and `pydantic-settings` are pulled in automatically.

```bash
# The API key is required (#157): set one, or opt out explicitly for local use
export BLUE_DATA_USER_API_KEY=secret          # or: export BLUE_DATA_USER_API_AUTH_DISABLED=true

# Defaults: 127.0.0.1:8003, ~/.blue-userdb data dir
blue-userdb-api

# Or with explicit configuration
BLUE_DATA_USER_SOURCE_DATA_DIR=/data/blue-userdb BLUE_DATA_USER_API_PORT=9000 blue-userdb-api

# Bind to all interfaces (scripts/start.sh does this by default)
bash scripts/start.sh

# Interactive docs
open http://localhost:8003/docs
```

The `BLUE_DATA_USER_SOURCE_*` settings can also be loaded from a `.env` file in the working directory (`pydantic-settings`); the `BLUE_DATA_USER_API_*` ones come from the environment only.

## Configuration reference

These share their names with the `blue-userdb` CLI's profile parameters but nothing else: the server reads the environment only, never `~/.blue-userdb/.profiles` or the selected profile. A CLI profile cannot reconfigure a running server.

| Variable | Default | Description |
|---|---|---|
| `BLUE_DATA_USER_SOURCE_DATA_DIR` | `~/.blue-userdb` | Directory where database files are stored |
| `BLUE_DATA_USER_SOURCE_ALLOWED_ORIGINS` | _(empty)_ | Comma-separated browser origins, besides the API's own, allowed to make state-changing requests |
| `BLUE_DATA_USER_SOURCE_SCHEMA_PATH` | _(empty)_ | Path to a custom `schema.json` for KB schema seeding |
| `BLUE_DATA_USER_SOURCE_METADATA_SCHEMA_PATH` | _(packaged `metadata_schema.json`)_ | Path to a custom metadata schema |
| `BLUE_DATA_USER_SOURCE_CONTACT_SCHEMA_PATH` | _(packaged `contact_schema.json`)_ | Path to a custom contact schema |
| `BLUE_DATA_USER_API_KEY` | _(none)_ | API key, sent as `X-API-Key` or `Authorization: Bearer`. Required: with none set, requests get `401` |
| `BLUE_DATA_USER_API_AUTH_DISABLED` | _(unset)_ | `true` runs without an API key (local development only) |
| `BLUE_DATA_USER_API_HOST` | `127.0.0.1` | Server bind address |
| `BLUE_DATA_USER_API_PORT` | `8003` | Server port (the family port map: registry 8000, doc 8001, web 8002, user 8003) |

**Cross-origin writes.** A state-changing request (`POST`, `PUT`, `PATCH`, `DELETE`) that carries a browser `Origin` header other than the API's own or one listed in `BLUE_DATA_USER_SOURCE_ALLOWED_ORIGINS` is refused with `403`. Without it, any web page the operator visits could make the browser post to a local API, e.g. reset a user; the JSON-only rule for writes blocks most of these too. Scripts and SDKs send no `Origin` and are unaffected.

## Authentication

The service follows the Blue data family's HTTP policy (`blue_data.server`, #157):

- **API key, required by default.** Every route except `/health`, the interactive docs and the two email-reply routes below needs `BLUE_DATA_USER_API_KEY`, sent as `X-API-Key: <key>` or `Authorization: Bearer <key>`. Without a valid key a request gets `401`. If no key is configured, requests are refused too, unless `BLUE_DATA_USER_API_AUTH_DISABLED=true`. The key is read from the process environment, not from `.env`.
- **JSON for writes.** A `POST`, `PUT`, `PATCH` or `DELETE` with a form, multipart or plain-text body (what a cross-site HTML form can send) gets `415`. Send `application/json`, or no body.
- **Open reply routes.** The reply form an email links to (`/interactions/{id}/respond`) and the inbound-email webhook (`/interactions/email/inbound`) need no key. A person clicking a link and a mail provider cannot send one. The interaction id in the link or reply address is their credential. The webhook reply route, `/interactions/{id}/response`, does need the key.

```bash
curl -H "X-API-Key: $BLUE_DATA_USER_API_KEY" http://localhost:8003/databases
```

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
| `POST` | `/databases/{name}` | Create a new user (file-backend defaults from `BLUE_DATA_USER_SOURCE_DATA_DIR`); `409` if it already exists |
| `GET` | `/databases/{name}` | Get user info and registry properties |
| `DELETE` | `/databases/{name}` | Delete a user and all their data |
| `POST` | `/databases/{name}/reset` | Clear a user's KB data, ingested documents, metadata, contacts and sessions, and reseed the schemas; the user stays registered. Files outside the data directory are never deleted; any such paths are listed under `not_deleted` (a `DELETE` only logs them) |

`POST /databases/{name}` takes an optional body choosing how the user's documents are searched, and nothing else: every store is a file under `BLUE_DATA_USER_SOURCE_DATA_DIR/sources/{name}/`, and any other key is rejected with `422`.

| Field | Values | Default |
|---|---|---|
| `doc_search_mode` | `vector` (by meaning), `hybrid` (meaning and keywords), `bm25` (keywords; its index lasts only for the server process that added the documents) | `vector` |
| `doc_embedding_model` | `openai` (`text-embedding-3-small`, needs `OPENAI_API_KEY`), `dummy` (a hash, no API calls; only with `bm25`) | `openai` |

`vector` or `hybrid` with `dummy` is rejected with `422`. `GET /databases/{name}` reports the choice under `doc_source`.

```bash
curl -H "X-API-Key: $BLUE_DATA_USER_API_KEY" -H 'Content-Type: application/json' \
  -d '{"doc_search_mode": "hybrid"}' -X POST http://localhost:8003/databases/alice
```

`name` must be 1–64 letters, digits, `_` or `-`, starting with a letter, digit or `_`. Other backends (Redis, Neo4j) are configured through the library or the CLI, not over REST.

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

`output_form` is `"json"` (default) or `"nl"` for a prose answer. `session` appends this query to an existing session (reused; `404` if unknown, `409` if it has ended); omit it to auto-create a new single-query session. `max_subqueries` (most sub-questions added, each answered by the KB's agent; `0` answers the query alone), `max_kb_turns` (most turns of that agent per sub-question, default 25) and `max_interaction_rounds` (default 3) bound the query's LLM calls, which number in the dozens at the defaults; see [Cost](guide.md#cost). A negative value, or `max_kb_turns` of `0`, is rejected with `422`.

**Response `200 OK`:**

```json
{
  "database": "alice",
  "query": "What skills does alice have?",
  "results": [
    {"skill": "Python"},
    {"skill": "SQL"},
    {"skill": "machine learning"}
  ],
  "session_id": "1c1919ff-9881-4429-8c52-ab6abae6ff1a"
}
```

`results` is the synthesized answer: one aggregated table for `"json"`, a string for `"nl"`. With `"include_expanded": true` it becomes `{"result": ..., "expanded": [...]}`, adding each sub-question with its raw results. `session_id` is always present — the session that was reused, or the one just auto-created.

### Sessions

| Method | Path | Description |
|---|---|---|
| `POST` | `/{name}/sessions` | Create a new session |
| `GET` | `/{name}/sessions` | List sessions for a database |
| `GET` | `/{name}/sessions/{session_id}` | Get one session's queries and interactions |
| `POST` | `/{name}/sessions/{session_id}/end` | End a session |

```bash
SID=$(curl -H "X-API-Key: $BLUE_DATA_USER_API_KEY" -s -X POST http://localhost:8003/alice/sessions | jq -r .session_id)
curl -H "X-API-Key: $BLUE_DATA_USER_API_KEY" -X POST http://localhost:8003/alice/query \
  -H 'Content-Type: application/json' \
  -d "{\"query\": \"What skills does alice have?\", \"session\": \"$SID\"}"

curl -H "X-API-Key: $BLUE_DATA_USER_API_KEY" http://localhost:8003/alice/sessions/$SID
curl -H "X-API-Key: $BLUE_DATA_USER_API_KEY" -X POST http://localhost:8003/alice/sessions/$SID/end
```

`GET .../sessions/{id}` returns `404` if unknown. `POST .../end` returns `404` if unknown; ending an already-ended session is idempotent (`200`). See [10-data-model.md](../design/10-data-model.md) §6 for the full record schema.

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

The answer is `{database, added, updated}`. A `name` already in use replaces that source and answers `200` with `updated: true`; otherwise the answer is `201`. Without a `name`, different text is a new source, and the same text updates its source.

### Metadata

| Method | Path | Description |
|---|---|---|
| `GET` | `/{name}/metadata` | List all metadata keys and values |
| `GET` | `/{name}/metadata/{key}` | Get a metadata value (nested keys use `.` separator) |
| `PUT` | `/{name}/metadata/{key}` | Set a metadata value |
| `DELETE` | `/{name}/metadata/{key}` | Delete a metadata key |

```bash
curl -H "X-API-Key: $BLUE_DATA_USER_API_KEY" -X PUT http://localhost:8003/alice/metadata/preferences.verbosity \
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
    "response_base_url": "http://localhost:8003",
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
    "response_base_url": "http://localhost:8003",
    "timeout": 300
  }
}
```

When an agent needs to ask Alice a question, the webhook fires a `POST` to `url` with:

```json
{
  "interaction_id": "<uuid>",
  "message": "Which delivery address should I use?",
  "response_url": "http://localhost:8003/interactions/<uuid>/response"
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
| `smtp_password` | no | `""` | SMTP auth password. Masked on reads; may be a `$VAR` reference |
| `smtp_use_tls` | no | `True` | Use STARTTLS |
| `reply_domain` | yes¹ | `"localhost"` | Domain for `Reply-To` address |
| `response_base_url` | yes¹ | — | Base URL of this API server |
| `subject` | no | `"A question for you"` | Email subject |
| `timeout` | no | `300` | Seconds to wait for reply |

¹ Not required when `inbound_provider` is `"stdio"`.

**Secrets.** `smtp_password`, a webhook's `url` and `headers`, and a notification `endpoint` are secret: every read path (REST, MCP tools, `blue-userdb contact list/get`) returns them masked as `***`. To keep `smtp_password`, a webhook's `url` or a header value out of the contacts store too, store a reference to an environment variable instead, e.g. `"smtp_password": "$BLUE_DATA_USER_CONTACT_SMTP_PASSWORD"`; it is resolved when a message is sent, and shown as-is on reads. Only variables named `BLUE_DATA_USER_CONTACT_*` can be referenced: any other name is refused when the contact is written, and fails the clarification when it is used, so a contact cannot read the server's other settings.

**`inbound_provider: "stdio"`** — development mode: prints email content to stdout and reads the reply from stdin. Useful for local testing without an SMTP server or inbound webhook.

```bash
curl -H "X-API-Key: $BLUE_DATA_USER_API_KEY" -X POST http://localhost:8003/alice/contacts \
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

Errors use FastAPI's standard body, a `detail` string (or, for request validation, FastAPI's list of field errors):

```json
{"detail": "User not found: 'nobody'"}
```

| HTTP status | Condition |
|---|---|
| 400 | Unknown inbound-email provider, or an interaction response that is missing its answer |
| 401 | Missing or wrong API key, or no key configured and `BLUE_DATA_USER_API_AUTH_DISABLED` not set |
| 403 | A state-changing request from a foreign browser origin |
| 415 | A state-changing request with a form, multipart or plain-text body (send `application/json`) |
| 404 | The user (database) does not exist (`UserNotFoundError`, on every route that names one), or the session (`SessionNotFoundError`), contact method (`ContactNotFoundError`), source or pending interaction does not |
| 409 | The user already exists (`UserExistsError`), the session has ended (`SessionEndedError`), or the interaction was already answered |
| 422 | Request validation (a malformed body, an unknown body key, an invalid database name, an inbound email the adapter cannot parse), or any other library error about the input (`QueryError`, `InteractionError`, e.g. an unsupported contact protocol) |
| 502 | The language model could not be reached or gave an unusable reply (`LLMError`) |
| 500 | Anything else — a bug; please report it |

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
        ├── sessions/          # session transcripts: vector store, and transcripts/<session id>/*.txt
        └── external_documents/  # chunks of added files (vector store)
```

Each JSON store has a `<file>.lock` beside it, and the knowledge graph a `.alice.lock`: cross-process write locks, removed with the user.

---

## Running tests

```bash
cd platform/api
pytest
```
