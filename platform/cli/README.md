# userdb CLI

Command-line interface for UserDb — a per-user data store with natural language querying.

## Installation

The library is not yet published to PyPI. Install both packages from source:

```bash
# 1. Install the library
cd lib && pip install -e . && cd ..

# 2. Install the CLI
cd platform/cli && pip install -e .
```

`click` and `rich` are pulled in automatically as CLI dependencies.

Set your OpenAI API key:

```bash
export OPENAI_API_KEY=sk-...
```

## Quick start

```bash
# Create a database
userdb user create alice

# Register a file as a queryable source (Type 1)
userdb --user alice import resume.txt

# Extract and store specific attributes (Type 2)
userdb --user alice import resume.txt \
  --query "What skills does the user have?" \
  --query "What is the user's most recent job title?"

# Query — Rich table (default)
userdb --user alice query "What jobs are suitable for me?"

# Query — natural language answer
userdb --user alice query "What jobs are suitable for me?" --format nl

# Query — raw JSON
userdb --user alice query "What jobs are suitable for me?" --format json
```

## Commands

### Global options

```
userdb [--user USER] [--data-dir DIR] COMMAND
```

| Option | Env var | Default | Description |
|---|---|---|---|
| `--user USER` | `USERDB_DATABASE` | — | User database ID |
| `--data-dir DIR` | `USERDB_DATA_DIR` | `~/.userdb` | Directory where database files are stored |

```bash
export USERDB_DATABASE=alice
userdb query "jobs suitable for me"
```

---

### `userdb query`

Execute a natural language query and print results.

```
userdb query TEXT [--session SESSION_ID] [--format (table|json|nl)]
```

| Argument / Option | Description |
|---|---|
| `TEXT` | Natural language query (required) |
| `--session SESSION_ID` | Session ID for query context and user interaction |
| `--format` | `table` (default) · `json` · `nl` |

**`--format table`** — Rich-formatted table (default)

```bash
userdb --user alice query "What skills does this user have?"
```

**`--format json`** — structured JSON array

```bash
userdb --user alice query "What skills does this user have?" --format json
```

```json
[
  {
    "query": "What technical skills does the user have?",
    "results": ["Python", "SQL", "machine learning"]
  }
]
```

**`--format nl`** — synthesized natural language answer

```bash
userdb --user alice query "What jobs are suitable for me?" --format nl
```

```
Based on your background in project management and technical skills in SQL and Python,
roles such as Technical Project Manager or Data Analyst would be a strong fit.
```

---

### `userdb import`

Import a file into a user database.

```
userdb import FILE [--query QUERY]...
```

| Argument / Option | Description |
|---|---|
| `FILE` | Path to file (required, must exist) |
| `--query QUERY` | Query to extract and store (Type 2). Repeat for multiple. Omit for source registration only (Type 1). |

**Type 1 — register source only**

```bash
userdb --user alice import resume.txt
# Registered: resume.txt
```

**Type 2 — extract and store attributes**

Each query is run through the LLM extractor. Results are stored under a schema-style attribute name derived from the query (e.g. `user_skills`, `recent_job_title`).

```bash
userdb --user alice import resume.txt \
  --query "What skills does the user have?" \
  --query "Does the user prefer remote work?"
# Imported: resume.txt (2 queries)
```

---

### `userdb user create`

Create a new user database.

```
userdb user create NAME
```

```bash
userdb user create alice
# Created database: alice
```

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | `UserDbError` — message printed to stderr |
| 2 | Bad arguments (Click) |

---

## Storage

Data is persisted under `~/.userdb/<user>/` by default:

```
~/.userdb/
└── alice/
    ├── data.json      # structured attribute entries
    └── vectors.json   # text entries for semantic search
```

Use `--data-dir` to store databases elsewhere:

```bash
userdb --data-dir /tmp/demo user create alice
userdb --data-dir /tmp/demo --user alice import resume.txt --query "What skills?"
userdb --data-dir /tmp/demo --user alice query "jobs suitable for me"
```
