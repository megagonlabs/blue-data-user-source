#!/usr/bin/env bash
# Install the blue-userdb MCP server, editable, together with the library it needs
# (and so the sibling repos, which lib/scripts/install.sh installs first).
# Usage: bash platform/mcp/scripts/install.sh        (run from anywhere; uses the active python3)
set -euo pipefail

MCP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "$MCP_ROOT/../../lib/scripts/install.sh"

echo "Installing blue-data-user-mcp (with dev tools)..."
python3 -m pip install -q -e "$MCP_ROOT[dev]"

echo "Done. Run: blue-userdb-mcp"
