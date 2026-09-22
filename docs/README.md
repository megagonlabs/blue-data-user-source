# Documentation

Landing page for all documentation in `blue-data-user-source` — what to read depends on what you're doing.

## Start here

| Doc | Read this if you want to... |
|---|---|
| [quickstart.md](quickstart.md) | Get a per-user knowledge store running in the next five minutes |
| [installation.md](installation.md) | Install any combination of the library, CLI, MCP server, and REST API, with all optional extras |
| [features.md](features.md) | See what the library can do, at a glance, with a short example per feature |

## Using it

| Doc | Read this if you want to... |
|---|---|
| [guide.md](guide.md) | Work through the Python library task by task — users, sources, querying, sessions, contact methods, metadata |
| [api-reference.md](api-reference.md) | Look up an exact method signature, parameter, or result type |
| [cli.md](cli.md) | Use the `blue-userdb` command-line tool — every command, with a full walkthrough |
| [mcp.md](mcp.md) | Connect Claude or another MCP client to a user's knowledge store — every tool, with Claude Desktop config |
| [api.md](api.md) | REST API — every endpoint, with request/response bodies |

## Building on it

| Doc | Read this if you want to... |
|---|---|
| [architecture.md](architecture.md) | Understand how the pieces fit together — the layered component diagram, the query and import paths, and how sessions/interaction work |
| [extending.md](extending.md) | Implement a new registry or KB storage backend, a new contact method protocol, or swap the LLM provider |

## Something's out of date

These pages are meant to track the actual current behavior of the code, not the plan for it. If you find one that's drifted, that's a bug in the docs — the underlying source of truth is always the code itself, [`lib/README.md`](../lib/README.md), [`platform/cli/README.md`](../platform/cli/README.md), [`platform/mcp/README.md`](../platform/mcp/README.md), and [`platform/api/README.md`](../platform/api/README.md) (the CLI, MCP, and REST pages here are written to stay in sync with those). Design rationale and decision history live under [`design/`](../design/), notably [`design/13-decision-log.md`](../design/13-decision-log.md).
