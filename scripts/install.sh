#!/usr/bin/env bash
# Install everything in this repo, editable, in dependency order:
#   the sibling repos → lib → CLI, MCP server, REST API.
# Expects ../blue-data, ../blue-data-kb-source and ../blue-data-doc-source beside this repo.
# Usage: bash scripts/install.sh        (run from anywhere; uses the active python3)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "$ROOT/lib/scripts/install.sh"

echo "Installing blue-data-user-cli, blue-data-user-mcp, blue-data-user-api..."
python3 -m pip install -q -e "$ROOT/platform/cli" -e "$ROOT/platform/mcp[dev]" -e "$ROOT/platform/api"

echo "Done. Commands: blue-userdb, blue-userdb-mcp, blue-userdb-api"
