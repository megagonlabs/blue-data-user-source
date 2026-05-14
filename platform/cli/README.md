# userdb CLI

Command-line interface for UserDb — a per-user data store with natural language query.

## Installation

The library is not yet published to PyPI. Install it from the local source first, then install the CLI:

```bash
# 1. Install the library from source
cd lib
pip install -e .
cd ..

# 2. Install the CLI from source
cd platform/cli
pip install -e .
```

`click` and `rich` are pulled in automatically as dependencies of the CLI package.

You also need an OpenAI API key for the reasoning layer:

```bash
export OPENAI_API_KEY=sk-...
```

## Quick start

```bash
# 1. Create a database for a user
userdb database create alice

# 2. Import a file (Type 1 — register as a queryable source)
userdb --database alice import ~/resume.txt

# 3. Import a file and extract specific data (Type 2)
userdb --database alice import ~/resume.txt \
  --query "What skills does the user have?" \
  --query "What is the user's most recent job title?"

# 4. Query in natural language
userdb --database alice query "What jobs are suitable for this user?"
```

## Commands

### Global options

```
userdb [--database DB] [--data-dir DIR] COMMAND
```

| Option | Env var | Default | Description |
|---|---|---|---|
| `--database DB` | `USERDB_DATABASE` | — | User database ID |
| `--data-dir DIR` | `USERDB_DATA_DIR` | `~/.userdb` | Directory where database files are stored |

```bash
export USERDB_DATABASE=alice
userdb query "jobs suitable for me"
```

---

### `userdb query`

Execute a natural language query and print results.

```
userdb query TEXT [--session SESSION_ID] [--format (table|json)]
```

| Argument / Option | Description |
|---|---|
| `TEXT` | Natural language query (required) |
| `--session SESSION_ID` | Session ID for query context and user interaction |
| `--format` | `table` (default, Rich-formatted) or `json` |

**Examples**

```bash
userdb --database alice query "What skills does this user have?"

userdb --database alice query "jobs suitable for me" --format json
```

```json
[
  {
    "query": "What skills does the user have?",
    "results": ["Python", "SQL", "machine learning"]
  }
]
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
| `--query QUERY` | Query to run over the file (Type 2). Repeat for multiple queries. Omit for source registration only (Type 1). |

**Type 1 — register source only**

```bash
userdb --database alice import ~/resume.txt
# Registered: /home/alice/resume.txt
```

**Type 2 — extract and store data**

```bash
userdb --database alice import ~/resume.txt \
  --query "What skills does the user have?" \
  --query "Does the user prefer remote work?"
# Imported: /home/alice/resume.txt (2 queries)
```

---

### `userdb database create`

Create a new user database.

```
userdb database create NAME
```

```bash
userdb database create alice
# Created database: alice
```

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | `UserDbError` — message printed to stderr |
| 2 | Bad arguments |

---

## Storage

Data is persisted to disk under `~/.userdb/<database>/` by default — two JSON files per database:

```
~/.userdb/
└── alice/
    ├── data.json      # structured key-value entries
    └── vectors.json   # text entries for semantic search
```

Data survives between separate `userdb` invocations. Use `--data-dir` to store databases elsewhere:

```bash
userdb --data-dir /tmp/demo --database alice database create alice
userdb --data-dir /tmp/demo --database alice import resume.txt --query "What skills?"
userdb --data-dir /tmp/demo --database alice query "jobs suitable for me"
```

To use a different backend (Redis, SQLite, etc.), implement `JSONSource` and `VectorSource` from `blue_data_user_source.interfaces` and pass a matching `store_factory` via the Python API.
