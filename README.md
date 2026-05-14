# blue-data-user-source

A per-user personal data store with natural language querying, LLM-based data extraction, and interactive data quality assurance.

## What it does

- **Import** documents and extract structured data from them using LLM-based extraction keyed by schema-style attribute names.
- **Query** the store in natural language; results are assessed for completeness and freshness and the user is prompted for clarification when needed.
- **Interact** via configurable contact channels (stdio, email, SMS, etc.) to verify stale data or fill in missing information, with responses persisted back to the store.
- **Output** query results as structured JSON, a Rich table, or a synthesized natural language answer.

## Repository layout

```
blue-data-user-source/
├── lib/                   # Python library (blue-data-user-source)
│   ├── src/blue_data_user_source/
│   └── tests/
├── platform/
│   └── cli/               # Command-line interface (userdb)
│       ├── src/blue_data_user_cli/
│       └── tests/
└── docs/design/           # Architecture and design documents
```

## Requirements

- Python 3.10+
- OpenAI API key

```bash
export OPENAI_API_KEY=sk-...
```

## Quick start

```bash
# Install the library
cd lib && pip install -e . && cd ..

# Install the CLI
cd platform/cli && pip install -e . && cd ../..

# Create a database
userdb user create alice

# Import a file — extract specific attributes (Type 2)
userdb --user alice import resume.txt \
  --query "What skills does the user have?" \
  --query "What is the user's most recent job title?"

# Query — structured output (default)
userdb --user alice query "What jobs are suitable for me?"

# Query — natural language answer
userdb --user alice query "What jobs are suitable for me?" --format nl
```

## Packages

| Package | Description |
|---|---|
| [lib/](lib/README.md) | `blue-data-user-source` — core Python library |
| [platform/cli/](platform/cli/README.md) | `blue-data-user-cli` — `userdb` CLI |
