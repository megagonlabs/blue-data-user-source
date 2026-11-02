# UDb — Repo Organization

## Directory Tree

```
blue-data-user-source/
│
├── README.md                            # one-line description, layout, quick start, package table
├── .gitignore
├── LICENSE                              # BSD 3-Clause with Attribution / NOTICE, as the other Blue repos
├── scripts/
│   └── install.sh                       # installs every package, editable, after the sibling repos
├── dev.envrc                            # local-only secrets (git-ignored via *.envrc)
├── treehouse.toml                       # local tooling config (git-ignored, like .python-version and .lavish/)
│
├── data/                                # sample input used by the docs and examples
│   └── resume.txt
│
├── design/                              # design documents (this directory)
│   ├── 01-overview.md … 13-decision-log.md
│   ├── design-process.md
│   └── repo-organization-template.md
│
├── docs/                                # user-facing documentation (start at docs/README.md)
│
├── examples/                            # runnable demos, each with a captured .output.txt
│   ├── backends/                        # memory / file / redis UserSource backends
│   ├── feature-demos/                   # one feature per script
│   ├── framework-demos/                 # LangGraph, direct and over MCP
│   ├── integration-demos/               # multi-step pipelines
│   └── scenario-demos/                  # end-to-end user scenarios
│
├── tools/
│   └── convert_schema.py                # one-off schema conversion helper
│
├── lib/                                 # Python library (blue-data-user-source)
│   ├── pyproject.toml                   # package metadata, dependencies, ruff/pyright config
│   ├── README.md
│   ├── scripts/
│   │   ├── build.sh                     # build the distribution package
│   │   ├── install.sh                   # sibling repos, then lib with its extras, editable
│   │   └── publish.sh                   # twine upload dist/*
│   ├── src/
│   │   └── blue_data_user_source/
│   │       ├── __init__.py              # re-exports UserSource and friends
│   │       ├── source.py                # UserSource — NLQI and main entry point
│   │       ├── file_user_source.py      # FileUserSource      (user/file)
│   │       ├── memory_user_source.py    # MemoryUserSource    (user/memory)
│   │       ├── types.py                 # shared result types and query models
│   │       │
│   │       ├── redis/
│   │       │   └── redis_user_source.py # RedisUserSource     (user/redis)
│   │       │
│   │       ├── data/
│   │       │   ├── manager.py           # UserDataManager
│   │       │   ├── paths.py             # backend-agnostic dot-path reads (get_path)
│   │       │   └── planner.py           # UserDataPlanner (placeholder, not on the query path)
│   │       │
│   │       ├── reasoning/
│   │       │   ├── reasoner.py          # UserQueryReasoner
│   │       │   └── metric.py            # UserDataMetric and its subclasses
│   │       │
│   │       ├── interaction/
│   │       │   ├── contact.py           # ContactManager, ContactMethod
│   │       │   ├── manager.py           # InteractionManager
│   │       │   ├── session.py           # SessionManager
│   │       │   ├── pending.py           # pending-interaction registry
│   │       │   └── email/               # SMTP, Mailgun, Postmark, Sendgrid adapters
│   │       │
│   │       └── data/                    # packaged schemas
│   │           ├── schema.json
│   │           ├── metadata_schema.json
│   │           └── contact_schema.json
│   │
│   └── tests/
│       ├── conftest.py                  # shared fixtures and in-memory doubles
│       ├── unit/                        # fast, offline, no API key; conftest.py fails any network access
│       │   ├── backends/  data/  doubles/  interaction/  reasoning/  sources/
│       └── benchmarks/                  # report-only LLM benchmarks, run live against a baseline
│           ├── common/                  # runners, scoring, run history, baseline check
│           ├── extraction/  querying/  reasoning/   # each with results/: history.jsonl + README.md
│           └── results/                 # committed snapshots of full score reports
│
└── platform/                            # external interface services
    ├── cli/                             # command-line interface (blue-userdb)
    │   ├── pyproject.toml               # declares the `blue-userdb` console script
    │   ├── README.md
    │   ├── scripts/
    │   │   ├── build.sh
    │   │   └── install.sh               # sibling repos, lib, then the CLI
    │   ├── src/
    │   │   └── blue_data_user_cli/
    │   │       ├── commands.py          # Click command groups
    │   │       ├── profile.py           # `blue-userdb profile` over blue_data.utils.config
    │   │       └── profile_spec.json    # this CLI's configuration parameters
    │   └── tests/unit/
    │
    ├── mcp/                             # MCP server (blue-userdb-mcp)
    │   ├── pyproject.toml
    │   ├── README.md
    │   ├── scripts/
    │   │   ├── build.sh
    │   │   └── install.sh
    │   ├── src/
    │   │   └── blue_data_user_mcp/
    │   │       ├── server.py            # the 23 MCP tools
    │   │       └── config.py            # UserSource singleton, configured from the environment
    │   └── tests/
    │
    └── api/                             # REST API (blue-userdb-api)
        ├── pyproject.toml
        ├── README.md
        ├── scripts/
        │   ├── build.sh
        │   ├── install.sh
        │   └── start.sh                 # run uvicorn bound to all interfaces
        ├── src/
        │   └── blue_data_user_api/
        │       ├── app.py               # FastAPI app, lifespan, router registration
        │       ├── auth.py              # X-API-Key dependency
        │       ├── config.py            # pydantic-settings over BLUE_DATA_USER_SOURCE_*
        │       ├── source.py            # UserSource construction
        │       └── routes/              # databases, query, data, metadata, contacts,
        │                                #   interactions, sessions
        └── tests/
```

---

## Layout Rationale

### `lib/` — the Python library

All core business logic lives under `lib/src/`. This is the only artifact published to PyPI. The `src/` layout within `lib/` prevents the package from being accidentally importable from the project root during development.

`lib/scripts/` provides two scripts:

| Script | Purpose |
|--------|---------|
| `build.sh` | Builds the wheel and sdist via `python -m build` |
| `publish.sh` | Publishes to PyPI via `twine upload` |

### Module-to-architecture mapping

| Module | Architecture layer |
|--------|--------------------|
| `source.py` | Natural Language Query Interface |
| `reasoning/` | Reasoning Layer |
| `data/` | Data Management Layer |
| `interaction/` | Interaction Layer |

### `platform/` — external interface services

Each external interface is an independent deployable unit under `platform/`. They depend on `lib` but contain no business logic — each is a thin adapter over `UserSource`. Separating them from `lib` keeps the library free of server and CLI dependencies and allows each service to be built, versioned, and deployed independently.

Each platform service follows the same internal structure:

| Path | Purpose |
|------|---------|
| `pyproject.toml` | Package metadata and dependencies (includes `lib` as a dependency) |
| `README.md` | Install, usage, and the interface's own reference |
| `scripts/build.sh` | Builds the distribution package (`mcp` and `api`; `cli` has no `scripts/`) |
| `scripts/install.sh` | Editable install with dev extras (`mcp` and `api`) |
| `src/<package>/` | Interface adapter code |
| `tests/` | Unit tests for the adapter layer (`cli` nests them under `tests/unit/`) |

Container images are described in [12-deployment-ops.md](12-deployment-ops.md); no
`Dockerfile` or `deploy.sh` is checked in yet.

### `types.py`

Shared result types and query models used across layers are defined in `lib/src/blue_data_user_source/types.py`. This prevents circular imports and provides a single source of truth for data contracts between components.

### `tests/`

Library tests live under `lib/tests/`. Each platform service has its own `tests/` directory for adapter-layer tests.

```
lib/tests/
├── conftest.py          # shared fixtures: UserSource instance, in-memory doubles
├── unit/
│   ├── backends/        # FileUserSource, MemoryUserSource, RedisUserSource
│   ├── data/            # UserDataManager, UserDataPlanner
│   ├── doubles/         # in-memory stand-ins shared across the suite
│   ├── interaction/     # ContactManager, InteractionManager, SessionManager
│   ├── reasoning/       # UserQueryReasoner, UserDataMetric
│   └── sources/         # connection lifecycle and protocol
└── benchmarks/          # report-only, per module
    ├── common/
    ├── extraction/
    ├── querying/
    └── reasoning/       # each with cases/ (YAML) and run.py
```

Platform adapter tests use the same in-memory doubles (imported from `lib/tests/`) and test only the translation layer: request parsing, response serialization, and error mapping.
