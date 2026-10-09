#!/usr/bin/env bash
# Install the blue-userdb CLI, editable, together with the library it needs.
# Usage: bash platform/cli/scripts/install.sh        (run from anywhere; uses the active python3)
set -euo pipefail

CLI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "$CLI_ROOT/../../lib/scripts/install.sh"

echo "Installing blue-data-user-cli..."
python3 -m pip install -q -e "$CLI_ROOT"

echo "Done. Run: blue-userdb --help"
