# UDb — Data Model

## Overview

UDb maintains two parallel per-user stores:

- **JSONSource** — structured key-value store; holds both user metadata and user data entries; supports JSONPath queries
- **VectorSource** — semantic key-value store; mirrors user data entries only; supports vector similarity search

Both stores are addressed by user ID. User data entries are written to both stores simultaneously (dual-write). The JSON store is the system of record.

> **Status in 1.0:** sections 1–5 below are the original design. 1.0 does not have the `data` namespace, the `VectorSource` mirror or dual-write; user data lives in a knowledge graph and in document stores instead. The model as built is in [§0](#0-as-built-in-10); §6 (sessions) is current.

---

## 0. As Built in 1.0

Each user has a `DataRegistry` (its own JSON store) holding these sources:

| Registry name | Class | Holds |
|---------------|-------|-------|
| `kb` | `KBSource` | The knowledge graph: the user's PERSON entity, extracted entities, facts (relations) and property values, each tied to a SOURCE node, plus one SOURCE node per added document (location, name, description, `original` date). Typed by the KB schema, `data/schema.json` |
| `metadata` | `JSONSource` | Four categories from `data/metadata_schema.json`, seeded with nulls at creation: `identity` (name, pronouns, locale, timezone), `preferences` (communication style, verbosity, language), `availability` (working hours, preferred channel, out of office, per-topic overrides) and `privacy` (data sharing, sensitive categories, retention days, consent level). Addressed by dotted key, e.g. `identity.timezone` |
| `contacts` | `JSONSource` | Contact methods at `<protocol>.<name>`: the protocol's fields from `data/contact_schema.json` plus `preference` (lower is preferred). Fields marked `"secret": true` are masked as `***` on read; a value may be a `$BLUE_DATA_USER_CONTACT_*` reference resolved when sending |
| `sessions` | `JSONSource` | Session, query and interaction records (§6) |
| `external_documents` | `DocumentDataSource` | Every added source's text, chunked and embedded; searched at query time |
| `session_content` | `DocumentDataSource` | Every resolved clarification as `Q: …\nA: …` text, shared across the user's sessions; searched at query time |

The outer registry (one per `UserSource`) lists the users and the store configs needed to reopen each one. Provenance comes from the stores themselves: KB facts point to their SOURCE node, document hits carry `"source": "external_documents" | "session_content"`, and a user's clarification reply is tagged `user-reply:<interaction_id>` with a fresh timestamp.

---

## 1. User ID

Each user database is addressed by a string user ID. The format is an opaque string; examples in this document use Firebase-style UIDs (e.g., `5WgRzdacRdOEvj8JBmCXFZSvWmH3`).

---

## 2. JSONSource

### 2.1 Structure

A user's JSON database is divided into two namespaces:

| Namespace | Contents |
|-----------|----------|
| `metadata` | Structured profile, contact methods, and source registry |
| `data` | Arbitrary user data entries |

---

### 2.2 User Metadata

#### General Profile

An extensible document. Required fields:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Display name |
| `picture` | string | Profile picture URL |
| `last_login` | ISO 8601 datetime | Most recent login timestamp |

Additional fields may be present depending on the authentication provider or import source.

**Example:**

```json
{
  "name": "Ada Lovelace",
  "picture": "https://example.com/avatar.jpg",
  "last_login": "2026-05-12T09:00:00Z",
  "timezone": "America/New_York"
}
```

#### Contact Methods

A list of contact method entries. Each entry:

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Channel type (e.g., `"email"`, `"phone"`, `"sms"`, `"x"`) |
| `value` | string | Channel-specific address or handle |
| `preference` | integer | Relative priority; lower value = higher priority |
| `verified` | boolean | Whether the channel has been verified |
| `last_use` | ISO 8601 datetime | Most recent use timestamp |

**Example:**

```json
[
  { "type": "email", "value": "ada@example.com",  "preference": 1, "verified": true, "last_use": "2026-05-12T09:00:00Z" },
  { "type": "phone", "value": "+15551234567",      "preference": 2, "verified": false, "last_use": "2026-05-12T10:00:00Z" },
  { "type": "x",     "value": "@ada",              "preference": 3, "verified": false, "last_use": "2026-05-12T11:00:00Z" }
]
```

#### Source Registry

A list of registered external source entries. Each entry:

| Field | Type | Description |
|-------|------|-------------|
| `source_id` | string | Unique identifier for the registered source |
| `source_type` | string | One of `"file"`, `"session"`, or other registered types |
| `location` | string | Filesystem path, URL, or session ID identifying the source |
| `registered_at` | ISO 8601 datetime | When the source was registered |
| `queries` | list[string] | Queries run at import time; empty for Type 1 registrations |

**Example:**

```json
[
  {
    "source_id": "src-abc123",
    "source_type": "file",
    "location": "~/resume.txt",
    "registered_at": "2026-05-01T10:00:00Z",
    "queries": ["What skills does the user have?"]
  },
  {
    "source_id": "src-xyz789",
    "source_type": "session",
    "location": "session-id-value",
    "registered_at": "2026-05-10T08:30:00Z",
    "queries": []
  }
]
```

---

### 2.3 User Data Entries

Arbitrary key-value data extracted from user sources or stored through queries. Keys are **not** unique — multiple entries may share the same key (e.g., `"skills"` populated independently from a resume and a session).

Each entry:

| Field | Type | Description |
|-------|------|-------------|
| `key` | string | Semantic label for the data (e.g., `"skills"`, `"job_preferences"`) |
| `value` | JSON array | One or more values associated with the key |
| `metadata` | object | Entry-level provenance metadata (see below) |

#### Entry Metadata

| Field | Type | Description |
|-------|------|-------------|
| `date` | ISO 8601 datetime | When the entry was created or last updated |
| `agent` | string | Identifier of the agent that created the entry |
| `source_id` | string \| null | ID of the source the entry was derived from; `null` for entries not tied to a specific source |

**Example:**

```json
{
  "key": "skills",
  "value": ["Python", "SQL", "machine learning"],
  "metadata": {
    "date": "2026-05-01T10:05:00Z",
    "agent": "import-agent-v1",
    "source_id": "src-abc123"
  }
}
```

**Example — same key, different source:**

```json
{
  "key": "skills",
  "value": ["project management", "stakeholder communication"],
  "metadata": {
    "date": "2026-05-10T09:15:00Z",
    "agent": "session-agent-v1",
    "source_id": "src-xyz789"
  }
}
```

---

## 3. VectorSource

The Vector store mirrors all user data entries from the JSON store. User metadata (profile, contact methods, source registry) is **not** stored in the Vector store.

### 3.1 Vector Entry

Each user data entry is stored as a vectorized record. Both the key and the value are independently embedded.

| Field | Type | Description |
|-------|------|-------------|
| `key_vector` | float[] | Embedding of the key string |
| `value_vector` | float[] | Embedding of the serialized value array |
| `key` | string | Original key, stored verbatim for retrieval |
| `value` | JSON array | Original value, stored verbatim for retrieval |
| `metadata` | object | Same metadata object as the corresponding JSONSource entry |

Semantic search may operate on key vectors, value vectors, or both, depending on query intent.

### 3.2 Embedding Model

The embedding model used to vectorize keys and values is pluggable and selected at deployment time. All entries within a single user database must be produced by the same model version; a model change requires re-embedding the entire database.

---

## 4. Synchronization

Every write to a user data entry is applied to both JSONSource and VectorSource within the same operation before the write is acknowledged (dual-write). JSONSource is the system of record.

User metadata writes (profile, contact methods, source registry) target JSONSource only.

---

## 5. Source Types

| `source_type` | Class | Description |
|---------------|-------|-------------|
| `"file"` | `FileSource` | Uploaded or local file (e.g., a resume) |
| `"session"` | `SessionSource` | Active or historical conversational session |

Additional source types may be registered as extensions.

> **Note:** the `"session"` source type above is an *import* mechanism — registering a pre-existing external conversation transcript as a Type 1/2 KB source, the same way a file is registered. It is a distinct concept from the `sessions` store described in §6, which tracks sessions *live*, as they're created through `execute_query`. The naming overlap is coincidental; nothing currently implements `SessionSource`.

---

## 6. Sessions, Queries, and Interactions

A **session** groups the queries and clarification interactions of one conversation. Unlike the JSONSource namespaces above (`metadata`, `data`), sessions live in their own per-user JSONSource (`sessions`) — a fourth built-in source alongside `kb`, `metadata`, and `contacts` — using the same dotted-path convention as Contact Methods (§2.2).

### 6.1 Session Record

Stored at `sessions.{session_id}`:

| Field | Type | Description |
|-------|------|-------------|
| `created_at` | ISO 8601 datetime | When the session was created |
| `ended_at` | ISO 8601 datetime \| `null` | When the session was ended, if it has been |
| `status` | `"active"` \| `"ended"` | Session lifecycle state |
| `doc_source_name` | string | Registry name of the `DocumentDataSource` its transcripts go to: `"session_content"`, shared by all of the user's sessions |
| `queries` | object | Query records, keyed by `query_id` (see §6.2) |

### 6.2 Query Record

Stored at `sessions.{session_id}.queries.{query_id}`. One query record per external `execute_query`/`execute_query_nl` call appended to the session:

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | The raw external query text |
| `output_form` | `"json"` \| `"nl"` | Requested output form for this query |
| `created_at` | ISO 8601 datetime | When the query was added to the session |
| `interactions` | object | Interaction records, keyed by `interaction_id` (see §6.3) |

### 6.3 Interaction Record

Stored at `sessions.{session_id}.queries.{query_id}.interactions.{interaction_id}`. One record per clarification round-trip with the user:

| Field | Type | Description |
|-------|------|-------------|
| `question` | string | The clarification question sent to the user |
| `response` | string \| `null` | The user's reply; `null` while pending |
| `contact` | object | `{"protocol": str, "name": str}` — which contact method handled this interaction |
| `status` | `"pending"` \| `"resolved"` \| `"timeout"` \| `"failed"` | Interaction lifecycle state. `"failed"`: the question could not be delivered (a contact missing a required field, an unreachable endpoint, a mail server error) |
| `error` | string | Only when `"failed"`: why delivery failed |
| `started_at` | ISO 8601 datetime | When the interaction was sent |
| `resolved_at` | ISO 8601 datetime \| `null` | When it resolved, timed out or failed |

`interaction_id` is the same id used to key the transport-level `pending_interactions` Future-correlation dict (webhook/email), and the `interaction` record in the outer registry through which a reply reaches another process (ADR-034) — see [04-detailed-architecture.md](04-detailed-architecture.md) and ADR-017 in [13-decision-log.md](13-decision-log.md).

**Example:**

```json
{
  "created_at": "2026-08-21T00:53:42Z",
  "ended_at": null,
  "status": "active",
  "doc_source_name": "session_content",
  "queries": {
    "8b62c38a-2cb6-482a-8bc8-66105dde4c4b": {
      "query": "what is my favorite color?",
      "output_form": "json",
      "created_at": "2026-08-21T00:53:45Z",
      "interactions": {
        "f1a2b3c4-...": {
          "question": "Could you tell me your favorite color?",
          "response": "blue",
          "contact": {"protocol": "stdio", "name": "default"},
          "status": "resolved",
          "started_at": "2026-08-21T00:53:46Z",
          "resolved_at": "2026-08-21T00:53:50Z"
        }
      }
    }
  }
}
```

### 6.4 Interaction Transcripts

Resolved interactions are additionally ingested as text (`"Q: {question}\nA: {response}"`) into the `session_content` `DocumentDataSource` (§6.1's `doc_source_name`), one document per interaction, shared by all of the user's sessions. This is a chunk/embed/search-backed store (from `blue-data-doc-source`), separate from the structured JSON record above — the JSON record is the system of record for session/query/interaction state; the `DocumentDataSource` exists for later recall of transcript text: in 1.0, `UserDataManager.execute_query` searches it for every sub-question (ADR-019); its use as a Context Expansion Source for query rewriting ([04-detailed-architecture.md](04-detailed-architecture.md)) is not built.

Unlike the sources in §5, `session_content` (like `external_documents`) is not reconstructed via the registry's generic `_class`/`connection` reflection — see ADR-016 in [13-decision-log.md](13-decision-log.md).
